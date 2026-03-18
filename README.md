# Mini Redis

Mini Redis는 Python으로 구현한 TCP 기반 Redis 서버입니다. 이번 프로젝트의 목표는 해시 테이블 기반 key-value 저장소를 직접 만들고, RESP2 프로토콜로 외부 클라이언트가 접근할 수 있는 Redis를 구현하는 데 있습니다.

## 프로젝트 목표

- 커스텀 해시 테이블 기반 저장소 구현
- RESP2 기반 TCP 서버와 명령 라우터 구현
- 외부에서 사용할 수 있는 CLI 제공
- TTL, 무효화, 상태 조회 같은 Redis형 동작 지원
- 단위 테스트와 통합 테스트로 핵심 기능 검증

기획서 기준 MVP는 `SET`/`GET`/`DEL`이 가능한 저장소, RESP2 서버, CLI, 테스트 가능한 실행 흐름입니다. 현재 구현은 여기에 만료 정책, 스냅샷 기반 persistence, 보조 명령까지 포함합니다.

## 핵심 기능

지원 명령:

- `PING`: 서버 연결 상태를 확인하고, 인자가 없으면 `PONG`, 있으면 전달한 값을 그대로 반환합니다.
- `ECHO`: 전달한 문자열 또는 바이트 값을 그대로 응답합니다.
- `SET`: key에 value를 저장하거나 같은 key의 기존 값을 덮어씁니다.
- `GET`: key에 저장된 값을 조회하고, 없거나 만료된 key면 nil을 반환합니다.
- `DEL`: 하나 이상의 key를 삭제하고 실제 삭제된 key 개수를 반환합니다.
- `EXPIRE`: key의 만료 시간을 초 단위로 설정합니다.
- `TTL`: key의 남은 TTL을 반환합니다. persistent key는 `-1`, 없거나 만료된 key는 `0`입니다.
- `PERSIST`: key에 설정된 TTL을 제거해 일반 key로 되돌립니다.
- `INFO`: 서버 상태, 처리 통계, 저장소 통계를 텍스트로 조회합니다.
- `COMMAND`: 지원 명령 메타 정보 대신 현재는 빈 배열을 반환합니다.
- `CLIENT SETINFO`: 클라이언트 라이브러리 이름 또는 버전을 서버에 전달합니다.
- `HELLO`: 프로토콜 핸드셰이크 정보를 반환하며 현재는 RESP2만 지원합니다.
- `QUIT`: `OK`를 반환한 뒤 현재 클라이언트 연결을 종료합니다.
- `EXIT`: `QUIT`와 동일하게 동작하며 팀 요구사항에 맞춰 함께 지원합니다.

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

### 해시 함수 선택 과정

현재 `HashTableStore`는 해시 함수를 외부에서 주입할 수 있게 열어두되, 기본값으로는 Python 내장 `hash()`를 사용합니다. 이번 결정의 목적은 "벤치마크 숫자가 가장 높은 해시 함수"를 고르는 것이 아니라, Python으로 구현한 Redis 스타일 저장소에서 가장 현실적이고 안정적인 기본 해시 전략을 정하는 데 있었습니다.

우리가 중요하게 본 기준은 아래와 같습니다.

- 외부 입력 키를 받는 서버 구조에서 충돌 유도 공격에 강해야 한다.
- Python 환경에서 실제로 빠르게 동작해야 한다.
- 현재 bucket-list chaining + resize 구조와 잘 맞아야 한다.
- 구현 복잡도와 외부 의존성을 불필요하게 늘리지 않아야 한다.
- 팀원이 이해하고 설명하기 쉬워야 한다.

후보를 비교하면, `xxHash`와 `MurmurHash3`는 raw hashing 속도는 빠르지만 비암호학적 해시라 외부 입력을 받는 저장소의 기본 해시로 두기에는 철학이 약했습니다. 반면 `SipHash`는 충돌 공격 방어 측면에서 Redis류 저장소의 기본 철학과 가장 잘 맞았습니다.

하지만 Python에서 별도 SipHash 구현을 직접 넣는 것은 오히려 비효율적일 수 있습니다. 현재 CPython의 내장 `hash()`는 C 레벨 구현이고, 로컬 Python 3.14 환경에서는 `sys.hash_info.algorithm == 'siphash13'` 기준이므로, 철학적으로는 SipHash를 따르면서도 구현은 가장 단순하고 현실적인 선택이 됩니다.

이 판단은 현재 저장소 구조와도 맞습니다. 우리 저장소는 충돌이 발생하면 같은 버킷 안에서 선형 탐색을 수행하므로, 악의적으로 충돌이 유도되면 버킷 내부 탐색 비용이 커집니다. resize는 평균적인 충돌을 줄여주지만, 공격적인 입력 분산 문제를 완전히 해결하지는 못합니다. 따라서 "조금 더 빠른 평균 해시"보다 "예측하기 어려운 입력 분산"이 더 중요하다고 봤습니다.

최종 결정은 아래와 같습니다.

- 기본 해시 함수는 Python 내장 `hash()`를 사용한다.
- 설계 철학은 SipHash 계열을 따른다고 설명한다.
- `xxhash`, `mmh3` 같은 외부 해시 라이브러리는 현재 단계에서는 도입하지 않는다.

즉, 결론은 "SipHash가 철학적으로 맞고, 현재 CPython에서는 `hash()`가 사실상 그 철학을 실용적으로 구현하고 있으므로 `hash()`를 채택한다"입니다.

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

### 최근 실행 결과

기준 일시: 2026-03-18 (KST)

- 전체 자동 테스트: `63개 테스트 통과`, 총 실행 시간 `8.057s`
- 기능 검증 범위:
  - 저장소 단위 테스트
  - RESP 파서 경계 입력 테스트
  - 서버 라우팅 테스트
  - TCP 통합 테스트
  - CLI 동작 테스트
  - 스냅샷 persistence 테스트

핵심적으로 확인된 항목:

- 외부 TCP 클라이언트가 `PING`, `SET`, `GET`, `DEL`, `EXPIRE`, `TTL`, `PERSIST`, `INFO`, `QUIT`, `EXIT`를 사용할 수 있는지 검증
- 잘못된 RESP, null bulk string, truncated bulk data, invalid bulk terminator 같은 엣지 케이스를 에러로 처리하는지 검증
- 만료 키의 lazy expiration, active expiration, TTL 제거, snapshot save/load가 기대대로 동작하는지 검증
- CLI interactive 모드에서 welcome/help/blank input 흐름이 정상 동작하는지 검증

### 벤치마크 결과

저장소 마이크로벤치마크 (`python3 benchmarks/storage_benchmark.py`)

- `HashTableStore`: 프로젝트의 실제 커스텀 해시 테이블 구현체
- `DictStore`: [`benchmarks/storage_benchmark.py`](/Users/choeyeongbin/mini_redis/benchmarks/storage_benchmark.py) 안에 정의된 비교용 어댑터로, Python 내장 `dict`를 그대로 감싼 로컬 벤치마크 전용 구현체
- 즉 아래 표의 `DictStore`는 외부 라이브러리나 별도 저장소가 아니라, "내장 `dict`를 기준선으로 삼은 비교 대상"입니다.

| 대상 | key 수 | SET | GET | DEL |
| --- | ---: | ---: | ---: | ---: |
| `HashTableStore` | 1,000 | 0.001023s | 0.000330s | 0.000324s |
| `DictStore` | 1,000 | 0.000063s | 0.000033s | 0.000035s |
| `HashTableStore` | 10,000 | 0.009240s | 0.003285s | 0.003134s |
| `DictStore` | 10,000 | 0.000589s | 0.000426s | 0.000346s |
| `HashTableStore` | 50,000 | 0.054173s | 0.016635s | 0.018080s |
| `DictStore` | 50,000 | 0.002936s | 0.001637s | 0.001711s |

해석:

- Python 내장 `dict` 자체 성능은 커스텀 해시 테이블보다 빠릅니다.
- 하지만 이번 프로젝트의 목적은 단순 최고 속도가 아니라, Redis 저장소의 충돌 처리, resize, TTL, 무효화, 통계 노출을 직접 제어하는 저장소를 구현하는 데 있습니다.

TCP 부하 테스트 (`python3 benchmarks/tcp_stress_test.py`)

안정적으로 통과한 기준:

- `PING`, `500 requests`, `concurrency=20`: `0.143s`, `3499.49 req/s`, `success=500`, `failure=0`
- `SET`, `500 requests`, `concurrency=20`: `0.093s`, `5356.86 req/s`, `success=500`, `failure=0`

고동시성에서 확인된 엣지 케이스:

- `PING`, `5000 requests`, `concurrency=500`: `success=4797`, `failure=203`, 주된 실패 원인은 `TimeoutError`
- `SET`, `3000 requests`, `concurrency=300`: `success=2917`, `failure=83`, 주된 실패 원인은 `TimeoutError`

즉, 현재 구현은 일반적인 기능 사용과 중간 수준의 TCP 요청에서는 정상 동작하지만, 높은 동시성 부하에서는 타임아웃 튜닝이나 서버 구조 개선이 더 필요합니다.

### 요구사항 대비 상태

- 기능 테스트와 엣지 케이스 테스트는 현재 저장소 안의 자동화 테스트로 검증했습니다.
- Mini Redis 자체의 저장소/서버 성능 측정 결과도 위와 같이 재현 가능합니다.
- 다만 "웹에서 MongoDB 직접 조회"와 "웹에서 Mini Redis(TCP) 조회"를 같은 데이터셋으로 반복 비교하는 자동화 벤치마크 결과는 현재 이 저장소 안에 별도 스크립트로 포함되어 있지 않습니다.
- 해당 비교는 현재 demo web 구조에서 수행할 수 있지만, README에 넣을 자동화 수치로 고정하려면 MongoDB 비교 전용 스크립트 또는 측정 로그를 추가로 관리하는 편이 맞습니다.

## 팀 역할 기준 정리

- 1번 팀원: 데모 웹과 MongoDB 비교 시나리오, 발표 흐름 정리
- 2번 팀원: redis-cli 스타일 CLI 구현
- 3번 팀원: TCP 서버, RESP2 파서, 명령 라우터 구현
- 4번 팀원: 해시 테이블 저장소, TTL 정책, 저장소 통계, 동시성 보호 구현

현재 저장소는 서버, CLI, 저장소, persistence까지 한 흐름으로 연결된 상태이며 README만으로 주요 기능과 검증 범위를 설명할 수 있게 정리했습니다.
