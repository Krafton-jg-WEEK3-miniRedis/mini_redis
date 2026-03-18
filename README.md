# Mini Redis

TCP 기반 Mini Redis 서버 실험 프로젝트입니다. RESP2 요청 파싱, 명령 라우팅, 해시테이블 기반 저장소, CLI, 단위 테스트와 통합 테스트를 포함합니다.

## 핵심 범위

기획서 기준 서버/라우터의 필수 명령은 아래입니다.

- `PING`
- `SET`
- `GET`
- `DEL`
- `INFO`
- `QUIT`
- `EXIT`

## 호환성 및 보조 명령

CLI 또는 Redis 클라이언트와의 연동 편의를 위해 아래 명령도 지원합니다.

- `ECHO`
- `EXPIRE`
- `COMMAND`
- `CLIENT SETINFO`
- `HELLO`

세부 규칙:

- `CLIENT SETINFO <LIB-NAME|LIB-VER> <value>` 형식만 허용합니다.
- `HELLO`는 인자 없이 호출하거나 `HELLO 2`만 허용합니다.
- `INFO`는 인자 없이 전체 정보를 반환하고, `INFO server`, `INFO stats` 섹션 조회를 지원합니다.
- `CLIENT`, `HELLO`, `INFO`의 잘못된 인자 개수는 `wrong number of arguments for '...' command` 형식의 에러를 반환합니다.

## 실행

```bash
python3 main.py --host 127.0.0.1 --port 6379
```

## 테스트

전체 테스트:

```bash
python3 -m unittest discover -s tests -v
```

테스트 구성:

- `tests/test_storage.py`: 해시 충돌, overwrite, lazy expiration, resize 검증
- `tests/test_router.py`: 명령 라우팅, 인자 수 오류, 보조 명령 에러 처리 검증
- `tests/test_server_integration.py`: TCP round trip, 잘못된 RESP, 연결 종료 동작 검증
- `tests/test_cli.py`: interactive CLI 안내문과 사용자 입력 흐름 검증

## 구조

- `mini_redis/resp.py`: RESP2 요청 파싱과 응답 직렬화
- `mini_redis/router.py`: 명령 디스패치와 응답 결정
- `mini_redis/storage.py`: 저장소 인터페이스와 해시테이블 엔진
- `mini_redis/server.py`: TCP 서버와 커넥션 루프
- `mini_redis/cli.py`: one-shot, interactive CLI

## 협업 경계

- 서버/라우터는 `KeyValueStore` 프로토콜의 `set/get/delete/expire`만 사용합니다.
- 저장소 내부 자료구조는 서버가 직접 참조하지 않습니다.
- 종료 명령은 Redis 호환성을 위해 `QUIT`, 팀 요구사항을 위해 `EXIT`를 함께 지원합니다.

## 다음 통합 포인트

- 4번 팀원의 해시테이블 저장소를 더 큰 명령 집합과 연결
- 2번 팀원의 CLI와 연동해 명령 round trip 검증
- 1번 팀원의 데모 웹에서 MongoDB 대비 응답시간 비교
