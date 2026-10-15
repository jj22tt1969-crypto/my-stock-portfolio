import os
import sys
import json
import gzip
import tempfile
import logging

# 프로젝트 루트 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.data.fundamental_collector import (
    DEFAULT_SNAPSHOT_PATH,
    DEFAULT_BASE_SNAPSHOT_PATH,
    validate_fundamental_snapshot
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def create_base_snapshot(
    input_path: str = DEFAULT_SNAPSHOT_PATH,
    output_path: str = DEFAULT_BASE_SNAPSHOT_PATH
) -> str:
    """
    현재 검증된 Full Runtime Snapshot을 읽어 schema와 integrity를 검증한 후,
    검증에 통과한 데이터만 Git tracked 대상인 gzip Base Snapshot으로 생성합니다.
    검증 실패 시 파일 생성을 즉시 중단하고 예외를 발생시킵니다.
    """
    logger.info(f"Checking input runtime snapshot at: {input_path}")
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input runtime snapshot not found: {input_path}")

    # 1. 원본 파일 로드
    raw_size_bytes = os.path.getsize(input_path)
    logger.info(f"Loading raw snapshot ({raw_size_bytes / (1024 * 1024):.2f} MB)...")
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 2. 엄격한 스냅샷 정합성 검증 (GEMINI.md 규칙 및 스키마 검증)
    logger.info("Validating snapshot integrity via validate_fundamental_snapshot()...")
    validate_fundamental_snapshot(data)

    stocks_count = len(data.get("stocks", {}))
    logger.info(f"Validation PASSED. Total valid stocks: {stocks_count}")
    if stocks_count < 2000:
        raise ValueError(f"Stock count too low for a full base snapshot ({stocks_count} < 2000).")

    # 3. Gzip 압축 및 임시 파일 생성
    output_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(output_dir, exist_ok=True)

    json_bytes = json.dumps(data, ensure_ascii=False, indent=None).encode("utf-8")
    compressed_data = gzip.compress(json_bytes, compresslevel=9)

    temp_fd, temp_path = tempfile.mkstemp(
        prefix="fundamental_base_snapshot_",
        suffix=".tmp.gz",
        dir=output_dir
    )
    try:
        with open(temp_fd, "wb") as f:
            f.write(compressed_data)

        # 4. 생성된 Gzip 파일 재로드 및 역검증
        logger.info("Verifying generated gzip snapshot...")
        with gzip.open(temp_path, "rt", encoding="utf-8") as f:
            reloaded_data = json.load(f)
            validate_fundamental_snapshot(reloaded_data)
            assert len(reloaded_data.get("stocks", {})) == stocks_count

        # 5. Atomic Replace
        os.replace(temp_path, output_path)
        final_size_bytes = os.path.getsize(output_path)
        final_size_mb = final_size_bytes / (1024 * 1024)
        compression_ratio = (final_size_bytes / raw_size_bytes) * 100

        logger.info(
            f"Successfully created base snapshot: {output_path} "
            f"({final_size_mb:.2f} MB, {compression_ratio:.1f}% of original, {stocks_count} stocks)"
        )
        return output_path

    except Exception as e:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise e


if __name__ == "__main__":
    try:
        out = create_base_snapshot()
        print(f"BASE_SNAPSHOT_CREATED={out}")
    except Exception as e:
        logger.error(f"Failed to create base snapshot: {e}")
        sys.exit(1)
