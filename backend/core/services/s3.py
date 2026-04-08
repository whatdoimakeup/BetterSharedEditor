import logging

import boto3
from botocore.exceptions import ClientError
from django.conf import settings

logger = logging.getLogger(__name__)


class S3Service:
    def __init__(self):
        self.bucket_name = settings.AWS_S3_BUCKET_NAME
        self.s3_client = boto3.client(
            "s3",
            endpoint_url=settings.AWS_S3_ENDPOINT_URL,
            aws_access_key_id=settings.AWS_S3_ACCESS_KEY,
            aws_secret_access_key=settings.AWS_S3_SECRET_KEY,
        )

    @staticmethod
    def _room_state_key(room_id: int) -> str:
        return f"rooms/{room_id}/state.bin"

    def upload_file(self, bucket_name, object_name, file_content):
        self.s3_client.put_object(Bucket=bucket_name, Key=object_name, Body=file_content)

    def download_file(self, bucket_name, object_name):
        try:
            response = self.s3_client.get_object(Bucket=bucket_name, Key=object_name)
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        return response["Body"].read()

    def file_exists(self, bucket_name, object_name) -> bool:
        try:
            self.s3_client.head_object(Bucket=bucket_name, Key=object_name)
            return True
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    def delete_file(self, bucket_name, object_name):
        self.s3_client.delete_object(Bucket=bucket_name, Key=object_name)

    def upload_room_state(self, room_id: int, state_bytes: bytes | None):
        self.upload_file(self.bucket_name, self._room_state_key(room_id), state_bytes or b"")

    def download_room_state(self, room_id: int):
        return self.download_file(self.bucket_name, self._room_state_key(room_id))

    def room_state_exists(self, room_id: int) -> bool:
        return self.file_exists(self.bucket_name, self._room_state_key(room_id))

    def delete_room_state(self, room_id: int):
        self.delete_file(self.bucket_name, self._room_state_key(room_id))


s3_service = S3Service()
