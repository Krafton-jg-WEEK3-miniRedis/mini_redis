# Mini Redis

Mini Redis는 Python으로 구현한 TCP 기반 Redis 서버입니다. 이번 프로젝트의 목표는 해시 테이블 기반 key-value 저장소를 직접 만들고, RESP2 프로토콜로 외부 클라이언트가 접근할 수 있는 Redis를 구현하는 데 있습니다. 발표와 데모는 이 README를 기준으로 진행할 수 있도록 프로젝트 목적, 구조, 실행 방법, 테스트 범위를 한 문서에 정리했습니다.

## 프로젝트 목표

- 커스텀 해시 테이블 기반 저장소 구현
- RESP2 기반 TCP 서버와 명령 라우터 구현
- 외부에서 사용할 수 있는 CLI 제공
- TTL, 무효화, 상태 조회 같은 Redis형 동작 지원
- 단위 테스트와 통합 테스트로 핵심 기능 검증

기획서 기준 MVP는 `SET`/`GET`/`DEL`이 가능한 저장소, RESP2 서버, CLI, 테스트 가능한 실행 흐름입니다. 현재 구현은 여기에 만료 정책, 스냅샷 기반 persistence, 보조 명령까지 포함합니다.

## 핵심 기능

지원 명령:

- `PING`
- `ECHO`
- `SET`
- `GET`
- `DEL`
- `EXPIRE`
- `TTL`
- `PERSIST`
- `INFO`
- `COMMAND`
- `CLIENT SETINFO`
- `HELLO`
- `QUIT`
- `EXIT`

동작 규칙:

- 프로토콜은 RESP2 기준입니다.
- `QUIT`와 `EXIT`는 모두 연결 종료 명령으로 지원합니다.
- `HELLO`는 인자 없이 호출하거나 `HELLO 2`만 허용합니다.
- `CLIENT`는 `CLIENT SETINFO <LIB-NAME|LIB-VER> <value>` 형식만 허용합니다.
- `INFO`는 전체 정보 또는 `server`, `stats`, `store` 섹션 조회를 지원합니다.
- `TTL`은 persistent key에 `-1`, 없거나 이미 만료된 key에 `0`을 반환합니다.

## 아키텍처

```text
CLI / Redis client
        |
        v
RESP2 TCP Server
        |
        v
Command Router
        |
        v
HashTableStore
```

현재 데모/배포 기준 컨테이너 구조:

```text
Demo Web Container
   |                      \
   | TCP/RESP2             \ MongoDB Query
   v                        v
Mini Redis Container    MongoDB Container
```

즉, 현재 환경은 Docker 위에서 아래 3개 컴포넌트가 함께 올라가 있는 구조입니다.

- Demo Web: 사용자 요청을 받아 비교 시나리오를 실행하는 프론트엔드 또는 API 진입점
- Mini Redis: 웹이 TCP로 직접 요청을 보내는 RESP2 기반 Redis 서버
- MongoDB: 웹이 직접 조회하는 문서 데이터 저장소

데모 웹은 같은 데이터에 대해 두 경로를 비교할 수 있습니다.

- 웹 -> MongoDB 직접 조회 경로
- 웹 -> Mini Redis TCP 요청 경로

즉, 현재 성능 비교는 웹이 두 저장소에 각각 직접 접근해서 측정하는 구조입니다. 발표에서는 같은 요청을 기준으로 "웹에서 MongoDB를 바로 조회한 경우"와 "웹에서 Mini Redis에 TCP로 직접 요청한 경우"의 응답 차이를 설명하면 됩니다.

구성 요소:

- `mini_redis/server.py`: TCP 서버, 연결 처리, 요청 루프, 스냅샷 save/load 연결
- `mini_redis/resp.py`: RESP2 요청 파싱과 응답 직렬화
- `mini_redis/router.py`: 명령 디스패치, 인자 검증, 에러 응답, `INFO` 구성
- `mini_redis/storage.py`: 커스텀 해시 테이블 저장소, TTL, 통계, 동시성 보호
- `mini_redis/persistence.py`: line-delimited JSON 스냅샷 저장/복구
- `mini_redis/cli.py`: interactive 모드와 one-shot 모드 CLI

## 저장소 설계

저장소는 Python 기본 `dict`를 그대로 쓰지 않고 `HashTableStore`를 직접 구현했습니다. 충돌 처리는 bucket-list chaining 방식으로 처리하고, 버킷 수는 2의 거듭제곱으로 유지합니다. 삽입 후 load factor가 임계치를 넘으면 resize와 rehash를 수행합니다.

### 해시 테이블 설계 철학

이번 저장소의 핵심 철학은 "Python에서 Redis의 핵심 동작을 설명 가능하고 제어 가능한 형태로 직접 구현한다"는 점입니다. 단순히 key-value를 저장하는 컬렉션을 만드는 것이 아니라, Redis형 저장소가 실제로 가져야 하는 정책까지 자료구조 수준에서 다루는 것을 목표로 했습니다.

그래서 Python의 기본 `dict`를 바로 저장소로 쓰지 않았습니다. `dict`는 범용 해시맵으로 매우 강력하지만, 이번 프로젝트에서는 충돌 처리, resize, TTL, expiration cleanup, 통계 노출 같은 정책을 우리가 직접 설계하고 설명할 수 있어야 했기 때문입니다.

설계 원칙은 아래에 가깝습니다.

- 저장소 인터페이스와 실제 구현을 분리해 서버가 내부 자료구조를 직접 알지 않도록 한다.
- Redis처럼 보여주는 데 그치지 않고, 충돌 처리와 만료 정책이 코드에서 명확하게 드러나도록 한다.
- Python 런타임에서는 linked list보다 관리가 단순하고 덜 비싼 bucket-list chaining을 택한다.
- TTL, 무효화, expired cleanup은 저장소 내부 책임으로 둔다.
- 저장소 상태를 `INFO`로 노출할 수 있도록 통계를 직접 관리한다.
- 고성능 미세 최적화보다 correctness와 설명 가능성을 우선한다.

즉, 현재 해시 테이블은 원본 Redis의 C 구현을 그대로 복제한 구조가 아니라, Redis의 핵심 요구사항을 Python 환경에 맞게 다시 선택하고 정리한 저장소 엔진입니다.

TTL 정책은 기본적으로 lazy expiration입니다. 조회나 접근 시점에 만료 여부를 확인해 즉시 제거합니다. 여기에 write-triggered active expiration을 추가해 쓰기 연산이 누적될 때 일부 버킷을 점진적으로 정리합니다. 이를 통해 접근되지 않는 expired key도 계속 쌓이지 않도록 했습니다.

동시성은 correctness 우선으로 설계했습니다. 저장소의 `set`, `get`, `delete`, `expire`, `ttl`, `persist`, `get_stats`, snapshot 관련 연산은 모두 `RLock` 아래에서 동작합니다.

`INFO store`에서 확인 가능한 저장소 통계:

- `keys`
- `capacity`
- `load_factor`
- `resize_count`
- `expired_removed_count`

## 실행 방법

서버 실행:

```bash
python3 main.py --host 127.0.0.1 --port 6379
```

스냅샷 persistence와 함께 실행:

```bash
python3 main.py --host 127.0.0.1 --port 6379 --snapshot-path ./data/mini_redis.snapshot
```

CLI interactive 모드:

```bash
python3 -m mini_redis.cli --host 127.0.0.1 --port 6379
```

CLI one-shot 모드:

```bash
python3 -m mini_redis.cli --host 127.0.0.1 --port 6379 SET team five
python3 -m mini_redis.cli --host 127.0.0.1 --port 6379 GET team
```

`redis-cli` 같은 외부 클라이언트로도 RESP2 요청을 보낼 수 있습니다.

도커 기반 통합 환경 관점에서 보면, demo web은 Mini Redis와 MongoDB에 각각 직접 붙는 비교 실행 주체입니다. 이때 Mini Redis 쪽 연결은 TCP/RESP2 기반이고, MongoDB 쪽 연결은 DB 직접 조회입니다. 따라서 README 발표 시에는 단일 서버 설명에 더해 "웹 -> Redis(TCP)"와 "웹 -> MongoDB" 두 경로의 비교 흐름을 함께 설명하는 것이 적절합니다.

## 테스트

전체 테스트:

```bash
python3 -m unittest discover -s tests -v
```

테스트 범위:

- `tests/test_storage.py`: 해시 충돌, overwrite, resize, TTL, lazy expiration, active expiration, 동시성 무결성 검증
- `tests/test_router.py`: 명령 라우팅, 인자 수 검증, 보조 명령 처리 검증
- `tests/test_resp.py`: RESP 파서 경계 입력과 오류 처리 검증
- `tests/test_server_integration.py`: TCP round trip, 종료 명령, 잘못된 RESP, 만료 명령, 스냅샷 복구 검증
- `tests/test_cli.py`: CLI interactive 흐름과 안내문 검증
- `tests/test_persistence.py`: 스냅샷 저장/복구와 잘못된 스냅샷 입력 검증

## 팀 역할 기준 정리

- 1번 팀원: 데모 웹과 MongoDB 비교 시나리오, 발표 흐름 정리
- 2번 팀원: redis-cli 스타일 CLI 구현
- 3번 팀원: TCP 서버, RESP2 파서, 명령 라우터 구현
- 4번 팀원: 해시 테이블 저장소, TTL 정책, 저장소 통계, 동시성 보호 구현

현재 저장소는 서버, CLI, 저장소, persistence까지 한 흐름으로 연결된 상태이며 README만으로 주요 기능과 검증 범위를 설명할 수 있게 정리했습니다.
