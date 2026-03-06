from rest_framework import status
from rest_framework.test import APITestCase

from authentication.models import CustomUser
from community.models import CommunityDiscussion


class CommunityApiTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="community-api@test.com",
            password="Password@123",
        )

    def test_overview_requires_authentication(self):
        response = self.client.get("/community/overview/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_overview_returns_payload_for_authenticated_user(self):
        self.client.force_authenticate(self.user)
        response = self.client.get("/community/overview/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("discussions", response.data)
        self.assertIn("topics", response.data)
        self.assertIn("events", response.data)
        self.assertIn("leaderboard", response.data)
        self.assertIn("stats", response.data)

    def test_overview_supports_query_filter(self):
        self.client.force_authenticate(self.user)
        response = self.client.get("/community/overview/?q=morning")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data["discussions"]), 1)

    def test_like_endpoint_increments_likes(self):
        self.client.force_authenticate(self.user)
        first = self.client.post("/community/discussions/1/like/")
        second = self.client.post("/community/discussions/1/like/")
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.data["likes"], first.data["likes"] + 1)

        persisted = CommunityDiscussion.objects.get(id="1")
        self.assertEqual(persisted.likes, second.data["likes"])

    def test_overview_reads_persisted_discussions(self):
        self.client.force_authenticate(self.user)
        self.client.get("/community/overview/")
        discussion = CommunityDiscussion.objects.get(id="1")
        discussion.title = "Persisted Title"
        discussion.save(update_fields=["title", "updated_at"])

        response = self.client.get("/community/overview/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = {item["title"] for item in response.data["discussions"]}
        self.assertIn("Persisted Title", titles)
