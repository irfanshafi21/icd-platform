
import json
import re
import time
from typing import Any, Callable, Optional

import streamlit as st
import streamlit.components.v1 as components


# ============================================================
# ICD PLATFORM VOICE ASSISTANT
# Persistent browser voice mode
#
# Behavior:
#   - Click START once.
#   - Assistant welcomes the user.
#   - It keeps listening continuously.
#   - Each completed utterance is sent to Streamlit.
#   - It automatically resumes listening after each command.
#   - It stays active until the user clicks STOP.
# ============================================================


PAGE_ALIASES = {
    "home": "🏠 Home",
    "dashboard": "📊 Dashboard",
    "candidates": "👥 Candidates",
    "candidate": "👥 Candidates",
    "resume screening": "📄 Resume Screening",
    "resume": "📄 Resume Screening",
    "interview": "🎤 Interview",
    "reports": "📈 Reports",
    "settings": "⚙️ Settings",
    "profile": "👤 Profile",
    "jobs": "📋 Jobs",
    "job": "📋 Jobs",
    "shortlisted": "⭐ Shortlisted",
    "ai insights": "🤖 AI Insights",
    "insights": "🤖 AI Insights",
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _clean(text: str) -> str:
    return (text or "").strip(" .,!?;:'\"")


def _find_page(command: str) -> Optional[str]:
    c = _norm(command)

    for alias in sorted(PAGE_ALIASES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", c):
            return PAGE_ALIASES[alias]

    return None


def _page_label(page: str) -> str:
    return re.sub(r"^[^\w]+", "", page).strip()


def _get_candidates() -> list:
    candidates = st.session_state.get("candidates", [])
    return candidates if isinstance(candidates, list) else []


def _find_candidate(name: str) -> Optional[dict]:
    needle = _norm(name)

    if not needle:
        return None

    for candidate in _get_candidates():
        candidate_name = _norm(str(candidate.get("name", "")))
        if candidate_name == needle:
            return candidate

    for candidate in _get_candidates():
        candidate_name = _norm(str(candidate.get("name", "")))
        if needle in candidate_name or candidate_name in needle:
            return candidate

    return None


# ============================================================
# COMMAND ACTIONS
# ============================================================

def _navigate(command: str) -> Optional[str]:
    c = _norm(command)
    page = _find_page(c)

    if not page:
        return None

    navigation_words = (
        "go to",
        "open",
        "show",
        "take me to",
        "navigate to",
        "switch to",
        "visit",
    )

    if any(word in c for word in navigation_words):
        st.session_state.current_page = page
        return f"I'll take you to {_page_label(page)}."

    return None


def _search_candidates(command: str) -> Optional[str]:
    match = re.match(
        r"^(?:search|find) candidates (?:for|with)\s+(.+)$",
        _norm(command),
        flags=re.I,
    )

    if not match:
        return None

    query = _clean(match.group(1))

    st.session_state.global_search = query
    st.session_state.current_page = PAGE_ALIASES["candidates"]

    return f"I'll search candidates for {query}."


def _open_candidate(command: str) -> Optional[str]:
    match = re.match(
        r"^open (?:candidate )?(.+)$",
        _norm(command),
        flags=re.I,
    )

    if not match:
        return None

    name = _clean(match.group(1))
    candidate = _find_candidate(name)

    st.session_state.current_page = PAGE_ALIASES["candidates"]

    if not candidate:
        st.session_state.global_search = name
        return (
            f"I couldn't find {name} exactly. "
            "I'll search for that candidate."
        )

    st.session_state.selected_candidate_key = str(
        candidate.get("id", "")
    )
    st.session_state.candidates_view = "profile"

    return (
        f"I'll open the profile for "
        f"{candidate.get('name', name)}."
    )


def _candidate_status_action(
    command: str,
    update_candidate_record: Optional[Callable[..., Any]],
) -> Optional[str]:

    if not update_candidate_record:
        return None

    c = _norm(command)

    patterns = [
        (r"^select (?:candidate )?(.+)$", "Selected"),
        (r"^reject (?:candidate )?(.+)$", "Rejected"),
        (r"^unreject (?:candidate )?(.+)$", "Waiting"),
    ]

    for pattern, status in patterns:
        match = re.match(pattern, c, flags=re.I)

        if not match:
            continue

        name = _clean(match.group(1))
        candidate = _find_candidate(name)

        if not candidate:
            st.session_state.current_page = PAGE_ALIASES["candidates"]
            st.session_state.global_search = name
            return (
                f"I couldn't find {name} exactly. "
                "I'll search for that candidate."
            )

        try:
            update_candidate_record(
                candidate["id"],
                {"status": status},
            )

            st.session_state.current_page = PAGE_ALIASES["candidates"]

            return (
                f"I'll mark "
                f"{candidate.get('name', name)} as {status}."
            )

        except Exception as error:
            print("CANDIDATE ACTION ERROR:", error)
            return (
                f"I found {candidate.get('name', name)}, "
                "but I couldn't update the candidate."
            )

    return None


def _bookmark_candidate(
    command: str,
    update_candidate_record: Optional[Callable[..., Any]],
) -> Optional[str]:

    if not update_candidate_record:
        return None

    match = re.match(
        r"^bookmark (?:candidate )?(.+)$",
        _norm(command),
        flags=re.I,
    )

    if not match:
        return None

    name = _clean(match.group(1))
    candidate = _find_candidate(name)

    if not candidate:
        st.session_state.current_page = PAGE_ALIASES["candidates"]
        st.session_state.global_search = name
        return (
            f"I couldn't find {name} exactly. "
            "I'll search for that candidate."
        )

    current = bool(candidate.get("bookmarked"))

    try:
        update_candidate_record(
            candidate["id"],
            {"bookmarked": not current},
        )

        if current:
            return (
                f"I'll remove the bookmark from "
                f"{candidate.get('name', name)}."
            )

        return (
            f"I'll bookmark "
            f"{candidate.get('name', name)}."
        )

    except Exception as error:
        print("BOOKMARK ERROR:", error)
        return (
            f"I found {candidate.get('name', name)}, "
            "but I couldn't update the bookmark."
        )


def _interview(command: str) -> Optional[str]:
    match = re.match(
        r"^(?:prepare|start) interview(?: for)?\s+(.+)$",
        _norm(command),
        flags=re.I,
    )

    if not match:
        return None

    name = _clean(match.group(1))
    candidate = _find_candidate(name)

    st.session_state.current_page = PAGE_ALIASES["interview"]

    if candidate:
        st.session_state.voice_interview_candidate_id = candidate["id"]
        return (
            f"I'll open the Interview page "
            f"for {candidate.get('name', name)}."
        )

    st.session_state.global_search = name
    return (
        f"I couldn't identify {name} exactly. "
        "I'll open Interview and search for that candidate."
    )


def _dangerous_command(command: str) -> Optional[str]:
    c = _norm(command)

    dangerous = (
        "delete all candidates",
        "clear all candidates",
        "remove all candidates",
    )

    if any(phrase in c for phrase in dangerous):
        st.session_state.voice_pending_confirmation = command
        return (
            "That action can remove candidate data. "
            "I will wait for your confirmation before doing it."
        )

    return None


def _execute_command(
    command: str,
    ask_assistant: Optional[Callable[..., Any]],
    update_candidate_record: Optional[Callable[..., Any]],
) -> str:

    for handler in (
        lambda: _navigate(command),
        lambda: _search_candidates(command),
        lambda: _open_candidate(command),
        lambda: _candidate_status_action(
            command,
            update_candidate_record,
        ),
        lambda: _bookmark_candidate(
            command,
            update_candidate_record,
        ),
        lambda: _interview(command),
        lambda: _dangerous_command(command),
    ):
        result = handler()
        if result:
            return result

    if ask_assistant:
        try:
            answer = ask_assistant(command)
            return str(answer) if answer is not None else (
                "I couldn't generate a response."
            )
        except Exception as error:
            print("ICD AI ERROR:", error)
            return (
                "I understood the request, "
                "but the AI assistant returned an error."
            )

    return (
        "I understood you, "
        "but I don't have an action for that yet."
    )


# ============================================================
# BROWSER VOICE UI
# ============================================================

def _render_voice_ui(
    assistant_active: bool,
    latest_response: str,
    latest_response_id: str,
) -> None:

    safe_response = json.dumps(
        latest_response or "",
        ensure_ascii=False,
    )
    safe_response_id = json.dumps(
        latest_response_id or "",
        ensure_ascii=False,
    )

    html = f"""
    <div style="font-family:Arial,sans-serif;padding:4px 0 8px;">
        <button id="icd-voice-start"
            style="
                width:100%;
                border:0;
                border-radius:8px;
                padding:11px;
                font-size:15px;
                cursor:pointer;
                background:#111827;
                color:white;
            ">
            🎙️ Start ICD Assistant
        </button>

        <button id="icd-voice-stop"
            style="
                width:100%;
                border:0;
                border-radius:8px;
                padding:9px;
                font-size:14px;
                cursor:pointer;
                margin-top:7px;
                background:#ef4444;
                color:white;
                display:none;
            ">
            ⏹️ Stop Assistant
        </button>

        <div id="icd-voice-status"
            style="
                margin-top:8px;
                font-size:12px;
                opacity:.8;
            ">
            {"Assistant active. Speak naturally." if assistant_active else "Assistant is idle."}
        </div>
    </div>

    <script>
    (() => {{
        const startBtn =
            document.getElementById("icd-voice-start");

        const stopBtn =
            document.getElementById("icd-voice-stop");

        const status =
            document.getElementById("icd-voice-status");

        const parentWindow = window.parent;

        const RESPONSE = {safe_response};
        const RESPONSE_ID = {safe_response_id};

        const ACTIVE_KEY =
            "icd_voice_assistant_active";

        const SPOKEN_RESPONSE_KEY =
            "icd_voice_spoken_response";

        let recognition = null;
        let manuallyStopped = false;
        let restarting = false;

        function setStatus(text) {{
            status.textContent = text;
        }}

        function speak(text) {{
            if (!text) return;

            try {{
                if ("speechSynthesis" in window) {{
                    window.speechSynthesis.cancel();

                    const utterance =
                        new SpeechSynthesisUtterance(text);

                    utterance.rate = 1.0;
                    utterance.pitch = 1.0;
                    utterance.volume = 1.0;

                    window.speechSynthesis.speak(utterance);
                }}
            }} catch (error) {{
                console.error("Speech output error:", error);
            }}
        }}

        function sendCommand(text) {{
            if (!text) return;

            const url =
                new URL(parentWindow.location.href);

            url.searchParams.set(
                "icd_voice_command",
                text
            );

            url.searchParams.set(
                "icd_voice_request",
                String(Date.now()) +
                "_" +
                Math.random().toString(36).slice(2)
            );

            parentWindow.location.href =
                url.toString();
        }}

        function getRecognitionClass() {{
            return (
                window.SpeechRecognition ||
                window.webkitSpeechRecognition
            );
        }}

        function startRecognition() {{
            const Recognition =
                getRecognitionClass();

            if (!Recognition) {{
                setStatus(
                    "Speech recognition is not supported. " +
                    "Use Chrome or Edge."
                );
                return;
            }}

            recognition =
                new Recognition();

            recognition.lang = "en-US";
            recognition.continuous = false;
            recognition.interimResults = false;
            recognition.maxAlternatives = 1;

            recognition.onstart = () => {{
                restarting = false;
                startBtn.style.display = "none";
                stopBtn.style.display = "block";
                setStatus(
                    "🎙️ Listening... speak naturally."
                );
            }};

            recognition.onresult = (event) => {{
                let transcript = "";

                for (
                    let i = event.resultIndex;
                    i < event.results.length;
                    i++
                ) {{
                    if (
                        event.results[i].isFinal
                    ) {{
                        transcript +=
                            event.results[i][0].transcript;
                    }}
                }}

                transcript =
                    transcript.trim();

                if (transcript) {{
                    setStatus(
                        "✅ Heard: " + transcript
                    );

                    sendCommand(transcript);
                }}
            }};

            recognition.onerror = (event) => {{
                if (
                    event.error === "aborted" ||
                    event.error === "no-speech"
                ) {{
                    return;
                }}

                setStatus(
                    "Microphone error: " +
                    event.error
                );
            }};

            recognition.onend = () => {{
                if (
                    manuallyStopped ||
                    localStorage.getItem(ACTIVE_KEY) !== "1"
                ) {{
                    startBtn.style.display = "block";
                    stopBtn.style.display = "none";
                    setStatus(
                        "Assistant is idle."
                    );
                    return;
                }}

                // The browser automatically returns here after
                // Each utterance ends here; the assistant stays active.
                if (!restarting) {{
                    restarting = true;

                    window.setTimeout(
                        () => {{
                            if (
                                localStorage.getItem(
                                    ACTIVE_KEY
                                ) === "1" &&
                                !manuallyStopped
                            {{
                                startRecognition();
                            }}
                        }},
                        250
                    );
                }}
            }};

            try {{
                recognition.start();
            }} catch (error) {{
                restarting = false;
                window.setTimeout(
                    () => {{
                        if (
                            localStorage.getItem(
                                ACTIVE_KEY
                            ) === "1" &&
                            !manuallyStopped
                        ) {{
                            startRecognition();
                        }}
                    }},
                    700
                );
            }}
        }}

        startBtn.onclick = () => {{
            try {{
                manuallyStopped = false;

            if (recognition) {{
                try {{
                    recognition.abort();
                }} catch (error) {{}}
            }}

            localStorage.setItem(
                ACTIVE_KEY,
                "1"
            );

            // Greeting is spoken once when the assistant is started.
            speak(
                "Welcome to ICD Platform. " +
                "How can I assist you?"
            );

            setStatus(
                "Starting microphone..."
            );

            window.setTimeout(
                () => {{
                    if (
                        localStorage.getItem(
                            ACTIVE_KEY
                        ) === "1"
                    ) {{
                        startRecognition();
                    }}
                }},
                900
            );
            }} catch (error) {{
                console.error("ICD voice start error:", error);
                setStatus("Voice error: " + error.message);
            }}
        }};

        stopBtn.onclick = () => {{
            manuallyStopped = true;

            localStorage.removeItem(
                ACTIVE_KEY
            );

            if (recognition) {{
                try {{
                    recognition.stop();
                }} catch (error) {{}}
            }}

            if (
                "speechSynthesis" in window
            ) {{
                window.speechSynthesis.cancel();
            }}

            startBtn.style.display = "block";
            stopBtn.style.display = "none";

            setStatus(
                "Assistant stopped."
            );
        }};

        // If the assistant was already active before a
        // Streamlit rerun, restore the listening loop.
        if (
            localStorage.getItem(
                ACTIVE_KEY
            ) === "1"
        ) {{
            startBtn.style.display = "none";
            stopBtn.style.display = "block";

            setStatus(
                "🎙️ Assistant active. Listening..."
            );

            window.setTimeout(
                () => {{
                    startRecognition();
                }},
                300
            );
        }}

        // Speak the latest response exactly once.
        if (
            RESPONSE &&
            RESPONSE_ID
        ) {{
            const previous =
                sessionStorage.getItem(
                    SPOKEN_RESPONSE_KEY
                );

            if (
                previous !== RESPONSE_ID
            ) {{
                sessionStorage.setItem(
                    SPOKEN_RESPONSE_KEY,
                    RESPONSE_ID
                );

                speak(RESPONSE);
            }}
        }}
    }})();
    </script>
    """

    components.html(
        html,
        height=145,
    )


# ============================================================
# MAIN RENDER FUNCTION
# ============================================================

def render_icd_voice_assistant(
    ask_assistant: Optional[Callable[..., Any]] = None,
    update_candidate_record: Optional[Callable[..., Any]] = None,
) -> None:

    command = st.query_params.get(
        "icd_voice_command"
    )

    request_id = st.query_params.get(
        "icd_voice_request"
    )

    last_request = st.session_state.get(
        "_icd_last_voice_request",
        "",
    )

    assistant_active = (
        st.session_state.get(
            "_icd_voice_mode",
            False,
        )
    )

    # A command coming from the browser means the assistant
    # should remain active after the Streamlit rerun.
    if (
        command
        and request_id
        and request_id != last_request
    ):

        st.session_state["_icd_last_voice_request"] = (
            request_id
        )

        st.session_state["_icd_voice_mode"] = True

        response = _execute_command(
            command,
            ask_assistant,
            update_candidate_record,
        )

        st.session_state["_icd_voice_response"] = response
        st.session_state["_icd_voice_response_id"] = request_id
        st.session_state["_icd_last_voice_command"] = command

        st.query_params.clear()

        st.rerun()

    latest_response = st.session_state.get(
        "_icd_voice_response",
        "",
    )

    latest_response_id = st.session_state.get(
        "_icd_voice_response_id",
        "",
    )

    assistant_active = st.session_state.get(
        "_icd_voice_mode",
        False,
    )

    with st.sidebar:

        st.markdown("---")

        st.markdown(
            "### 🎙️ ICD Voice Assistant"
        )

        st.caption(
            "Start once. Speak naturally. "
            "The assistant stays active until you stop it."
        )

        _render_voice_ui(
            assistant_active,
            latest_response,
            latest_response_id,
        )

        last_command = st.session_state.get(
            "_icd_last_voice_command",
            "",
        )

        if last_command:
            st.caption(
                f"Last command: {last_command}"
            )

        if latest_response:
            st.success(
                f"ICD Assistant: {latest_response}"
            )

        pending = st.session_state.get(
            "voice_pending_confirmation"
        )

        if pending:

            st.warning(
                "Confirmation required."
            )

            col1, col2 = st.columns(2)

            with col1:

                if st.button(
                    "✅ Confirm",
                    key="icd_voice_confirm",
                    use_container_width=True,
                ):

                    st.session_state.voice_pending_confirmation = None

                    st.info(
                        "Please use the existing ICD confirmation control."
                    )

                    st.rerun()

            with col2:

                if st.button(
                    "❌ Cancel",
                    key="icd_voice_cancel",
                    use_container_width=True,
                ):

                    st.session_state.voice_pending_confirmation = None

                    st.info(
                        "Cancelled."
                    )

                    st.rerun()
