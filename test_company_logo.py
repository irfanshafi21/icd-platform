import base64
import io
import unittest
from PIL import Image
from fastapi import HTTPException
from web_app import _validated_logo, CompanyRegistration


class CompanyLogoTests(unittest.TestCase):
    def test_normalizes_and_resizes(self):
        source = io.BytesIO()
        Image.new('RGB', (1000, 500), 'teal').save(source, 'JPEG')
        result = _validated_logo(base64.b64encode(source.getvalue()).decode())
        with Image.open(io.BytesIO(base64.b64decode(result))) as image:
            self.assertEqual(image.format, 'PNG')
            self.assertEqual(image.size, (512, 256))

    def test_rejects_invalid_content(self):
        for value in ['invalid', base64.b64encode(b'<svg/>').decode(), 'a' * 3_000_001]:
            with self.assertRaises(HTTPException):
                _validated_logo(value)

    def test_optional_and_registration_field(self):
        self.assertEqual(_validated_logo(''), '')
        data = CompanyRegistration(company_name='Test', contact_name='Tester', business_email='test@example.test', logo_base64='logo')
        self.assertEqual(data.model_dump()['logo_base64'], 'logo')
