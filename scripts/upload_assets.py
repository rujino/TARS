"""CLI utility to manage and upload character assets to SeaweedFS / S3 object storage."""

from __future__ import annotations

import argparse
import mimetypes
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from tars.config import get_settings


def get_s3_client():
    """Create S3 client using TARS global settings."""
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    )


def ensure_bucket_exists(s3_client, bucket_name: str) -> None:
    """Ensure the target assets bucket exists, creating it if needed."""
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        print(f"Bucket '{bucket_name}' already exists.")
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")
        if error_code in ("404", "NoSuchBucket", "NotFound"):
            print(f"Creating bucket '{bucket_name}'...")
            s3_client.create_bucket(Bucket=bucket_name)
            print(f"Bucket '{bucket_name}' created successfully.")
        else:
            print(f"Error checking bucket '{bucket_name}': {exc}", file=sys.stderr)
            raise


def list_assets(s3_client, bucket_name: str) -> None:
    """List all assets stored in the target bucket."""
    print(f"\n--- Stored Assets in Bucket: '{bucket_name}' ---")
    try:
        paginator = s3_client.get_paginator("list_objects_v2")
        count = 0
        for page in paginator.paginate(Bucket=bucket_name):
            for item in page.get("Contents", []):
                count += 1
                size_kb = item["Size"] / 1024
                print(f"  [{count:2d}] {item['Key']} ({size_kb:.1f} KB, Modified: {item['LastModified']})")
        if count == 0:
            print("  (No objects found in bucket)")
        else:
            print(f"Total: {count} assets.\n")
    except ClientError as exc:
        print(f"Failed to list assets: {exc}", file=sys.stderr)


def upload_directory(s3_client, bucket_name: str, src_dir: Path) -> None:
    """Upload all files from a directory maintaining relative path keys."""
    if not src_dir.exists() or not src_dir.is_dir():
        print(f"Source directory '{src_dir}' does not exist.", file=sys.stderr)
        return

    files = [p for p in src_dir.rglob("*") if p.is_file() and not p.name.startswith(".")]
    if not files:
        print(f"No asset files found to upload in '{src_dir}'.")
        return

    print(f"\nUploading {len(files)} files from '{src_dir}' to S3 bucket '{bucket_name}'...")
    uploaded = 0
    for file_path in sorted(files):
        # Build relative key, e.g. characters/vera/idle.png
        rel_key = file_path.relative_to(src_dir).as_posix()
        content_type, _ = mimetypes.guess_type(file_path.name)
        if not content_type:
            content_type = "application/octet-stream"

        try:
            with open(file_path, "rb") as f:
                s3_client.put_object(
                    Bucket=bucket_name,
                    Key=rel_key,
                    Body=f,
                    ContentType=content_type,
                )
            print(f"  [OK] {rel_key} ({content_type})")
            uploaded += 1
        except Exception as exc:
            print(f"  [FAILED] {rel_key}: {exc}", file=sys.stderr)

    print(f"Upload complete. {uploaded}/{len(files)} files successfully uploaded.\n")


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="TARS Character Assets Object Storage Manager")
    parser.add_argument(
        "--bucket",
        default=settings.s3_assets_bucket_name,
        help=f"Target S3 bucket name (default: {settings.s3_assets_bucket_name})",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path("./assets"),
        help="Local assets directory to upload (default: ./assets)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all assets currently stored in the bucket",
    )
    parser.add_argument(
        "--init-bucket",
        action="store_true",
        help="Ensure target bucket exists without uploading files",
    )

    args = parser.parse_args()
    s3 = get_s3_client()

    ensure_bucket_exists(s3, args.bucket)

    if args.list:
        list_assets(s3, args.bucket)
        return

    if args.init_bucket:
        print(f"Bucket '{args.bucket}' is initialized and ready.")
        return

    upload_directory(s3, args.bucket, args.dir)
    list_assets(s3, args.bucket)


if __name__ == "__main__":
    main()
