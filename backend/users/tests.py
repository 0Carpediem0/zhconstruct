from django.contrib.auth import get_user_model
from django.test import TestCase


class UserModelTests(TestCase):
    def test_create_user(self):
        user = get_user_model().objects.create_user(
            username='resident',
            password='test-password',
        )

        self.assertEqual(user.username, 'resident')
        self.assertTrue(user.check_password('test-password'))
