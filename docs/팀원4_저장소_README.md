# Mini Redis - Team 4 Storage README

이 문서는 Mini Redis 프로젝트 전체 소개 문서가 아니라, 4번 팀원이 맡은 저장소 엔진 구현 내용을 설명하기 위한 README입니다.  
중심 내용은 커스텀 해시 테이블 저장소, TTL 정책, 무효화 방식, 동시성 보호, 테스트와 협업 인터페이스입니다.

## 담당 범위

4번 팀원으로서 맡은 범위는 저장소 엔진입니다.

- Python 기본 `dict`를 직접 저장소로 사용하지 않고, 별도의 해시 테이블 구조 구현
- `SET`, `GET`, `DEL` 핵심 로직 구현
- overwrite 지원
- 여러 키 삭제 시 삭제 개수 반환
- `EXPIRE`, `TTL`, `PERSIST`를 통한 만료 정책 제어
- lazy expiration 구현
- write-triggered active expiration 추가
- 저장소 통계 제공
- 멀티스레드 환경에서의 저장소 무결성 보호
- 저장소 단위 테스트 작성

핵심 구현 파일은 [`mini_redis/storage.py`](../mini_redis/storage.py) 입니다.

## 구현 목표

이번 저장소 구현의 목표는 단순히 key-value를 저장하는 컬렉션을 만드는 것이 아니라, Redis형 저장소가 실제로 가져야 하는 기능을 Python에서 설명 가능하고 안정적으로 구현하는 것이었습니다.

중요하게 본 기준은 아래와 같습니다.

- 충돌 처리 구조가 코드에서 명확히 보여야 한다.
- 서버가 바로 붙을 수 있도록 저장소 인터페이스가 분리되어야 한다.
- TTL과 무효화 정책을 저장소 자체가 책임져야 한다.
- 상태를 외부에서 확인할 수 있어야 한다.
- 멀티스레드 환경에서도 상태가 깨지지 않아야 한다.

## 왜 `dict` 대신 커스텀 해시 테이블인가

Python에서 성능만 보면 일반적으로 `dict`가 더 강력합니다. 하지만 이번 구현의 목적은 파이썬 내장 컬렉션을 그대로 쓰는 것이 아니라, Mini Redis의 저장소 동작을 직접 설계하고 제어하는 것이었습니다.

커스텀 해시 테이블을 사용한 이유는 다음과 같습니다.

- 충돌 처리 방식을 직접 구현하고 설명할 수 있습니다.
- resize, load factor, TTL, expiration cleanup 같은 정책을 저장소 수준에서 제어할 수 있습니다.
- `DEL`, `EXPIRE`, `TTL`, `PERSIST` 같은 Redis형 동작을 자료구조와 함께 설명할 수 있습니다.
- `INFO`로 노출할 저장소 통계(`capacity`, `load_factor`, `resize_count`, `expired_removed_count`)를 직접 관리할 수 있습니다.
- 저장소를 실험 가능한 엔진으로 유지할 수 있습니다.

즉, `dict`는 범용적으로 매우 빠른 해시맵이고, 현재 구현은 Redis형 정책을 가진 저장소 엔진입니다.

## 저장소 설계 원리

이 저장소는 원본 Redis의 C 구현을 그대로 복제하는 방식이 아니라, Python 런타임 특성에 맞게 다시 설계한 구조입니다.

설계 원리는 다음과 같습니다.

- 저장소 인터페이스와 실제 구현을 분리한다.
- 충돌 처리는 명시적으로 구현하되, Python에서 지나치게 비싼 구조는 피한다.
- 버킷 수는 직접 관리하고, load factor 기반으로 resize 한다.
- TTL과 무효화 정책은 저장소 내부 책임으로 둔다.
- 저장소 상태를 통계로 노출한다.
- 동시성은 고성능보다 correctness를 우선한다.

## 자료구조 구성

저장소 핵심 자료구조는 [`mini_redis/storage.py`](../mini_redis/storage.py) 에 정의되어 있습니다.

- `KeyValueStore`
- `HashEntry`
- `StoreStats`
- `HashTableStore`

각 역할은 다음과 같습니다.

`KeyValueStore`는 저장소 인터페이스입니다. 서버는 저장소 내부 구현을 직접 알 필요 없이 아래 메서드만 호출합니다.

- `set`
- `get`
- `delete`
- `expire`
- `ttl`
- `persist`
- `get_stats`

`HashEntry`는 실제 저장 단위입니다. 하나의 entry는 아래 정보를 가집니다.

- `key`
- `value`
- `expires_at`

`StoreStats`는 저장소 상태를 나타내는 구조입니다. 현재 아래 통계를 제공합니다.

- `size`
- `capacity`
- `load_factor`
- `resize_count`
- `expired_removed_count`

`HashTableStore`는 실제 해시 테이블 엔진입니다. 버킷 배열, TTL 정책, 통계, 락, resize 정책을 모두 관리합니다.

현재 내부 구조는 아래와 같습니다.

- `_buckets`: `list[list[HashEntry]]`
- `_size`: 현재 살아 있는 key 개수
- `_resize_count`: resize 발생 횟수
- `_expired_removed_count`: 만료로 제거된 key 수
- `_lock`: 전역 `RLock`
- `_clock`: TTL 판정 기준 시간
- `_hash_function`: 현재 Python 내장 `hash()`

## 버킷 구조와 타입 제한

버킷 컨테이너는 Python `list`를 사용합니다. 즉 현재 해시 테이블은 `list[list[HashEntry]]` 구조이며, 충돌이 발생하면 같은 버킷의 리스트 안에 여러 entry가 저장됩니다.

하지만 저장소 계약은 자료형 자유 구조로 열어두지 않고 `bytes -> bytes` 형태로 제한했습니다. 즉 현재 저장소는 일반적인 Python 컬렉션이 아니라, Redis 프로토콜과 바로 맞물리는 바이너리 key-value 저장소를 전제로 설계했습니다.

이렇게 제한한 이유는 다음과 같습니다.

- RESP를 통해 서버로 들어오는 데이터가 기본적으로 `bytes` 이므로, 저장소가 같은 타입을 그대로 받도록 하면 서버와 저장소 연결이 단순해집니다.
- key와 value를 모두 `bytes`로 고정하면 해시 계산, key 비교, 응답 직렬화 흐름을 일관되게 유지할 수 있습니다.
- 문자열, 숫자, 객체 등 다양한 타입을 허용할 경우 필요한 변환 규칙과 예외 처리가 늘어나는데, 이를 줄여 저장소 책임을 명확하게 유지할 수 있습니다.

따라서 현재 구조는 “리스트를 사용하는 범용 컨테이너”가 아니라, Python으로 구현한 Redis형 바이너리 저장소입니다.

## 구현 과정과 설계 전환

초기에는 separate chaining 기반 구조로 충돌 처리와 TTL의 기본 동작을 먼저 검증했습니다. 이 과정에서 Mini Redis 저장소가 실제로 가져야 할 요구사항이 명확해졌습니다.

- 데이터가 증가해도 충돌이 과도하게 누적되지 않아야 한다.
- load factor를 기준으로 resize와 rehash가 가능해야 한다.
- 만료 데이터가 접근 시점에 정리되는 lazy expiration이 필요하다.
- `DEL`, `EXPIRE`, `TTL`, `PERSIST` 같은 무효화 제어가 필요하다.
- 상태를 외부에서 확인할 수 있는 통계가 필요하다.
- 서버 환경에서 동시에 접근해도 상태가 깨지지 않아야 한다.

이후 가장 큰 설계 전환은 “Redis처럼 보이는 구조”보다 “Python에서 덜 느리고 더 관리하기 쉬운 구조”를 택한 것입니다.

- linked list chaining 대신 bucket-list chaining으로 전환했습니다.
- 버킷 내부를 `list[HashEntry]`로 바꿔 포인터 추적 비용을 줄였습니다.
- load factor 기반 resize를 추가했습니다.
- TTL은 `HashEntry.expires_at`으로 단순하게 관리했습니다.
- `get_stats()`를 통해 저장소 상태를 원자적으로 읽을 수 있게 했습니다.
- lazy expiration의 한계를 보완하기 위해 write-triggered active expiration을 추가했습니다.

즉, 현재 저장소는 Redis의 핵심 기능을 유지하되, 구현은 Python 환경에 맞게 다시 선택한 구조입니다.

## 해시 테이블 관리 방식

현재 해시 테이블은 bucket-list chaining 방식으로 동작합니다.

1. 해시 함수로 버킷 인덱스를 계산합니다.
2. 해당 버킷 안의 리스트에서 key를 순차 탐색합니다.
3. 같은 key가 있으면 overwrite 합니다.
4. 없으면 새 `HashEntry`를 추가합니다.

버킷 수는 항상 2의 거듭제곱으로 유지합니다. 인덱스 계산은 `%` 대신 bitmask 방식으로 처리합니다.

또한 `load factor = size / capacity`를 기준으로 저장소를 관리합니다. 삽입 후 load factor가 임계치를 넘으면 버킷 수를 2배로 늘리고, 기존 live entry를 새 버킷 구조에 다시 배치합니다. 이 과정에서 이미 만료된 key는 다시 넣지 않습니다.

## 주요 함수 동작 방식

핵심 함수는 모두 [`mini_redis/storage.py`](../mini_redis/storage.py) 에 구현되어 있습니다.

`set(key, value)`
- key가 들어갈 버킷을 찾습니다.
- 같은 key가 있으면 값을 overwrite 하고 TTL을 제거합니다.
- 없으면 새 `HashEntry`를 추가합니다.
- 삽입 이후 load factor가 임계치를 넘으면 resize를 수행합니다.

`get(key)`
- 버킷에서 key를 찾습니다.
- 없으면 `None`을 반환합니다.
- 만료된 key라면 즉시 삭제하고 `None`을 반환합니다.
- 살아 있는 key만 value를 반환합니다.

`delete(keys)`
- 여러 key를 순회하며 각 버킷에서 삭제를 수행합니다.
- 실제로 삭제된 live key 수만 정수로 반환합니다.
- 이미 만료된 key는 내부적으로 정리되지만 삭제 개수에는 포함하지 않습니다.

`expire(key, seconds)`
- 살아 있는 key에 대해 `expires_at = now + seconds`를 설정합니다.
- key가 없거나 이미 만료되었다면 실패합니다.
- 실제 삭제는 lazy expiration 또는 active expiration 시점에 처리됩니다.

`ttl(key)`
- 만료 시간이 없으면 `-1`을 반환합니다.
- key가 없거나 이미 만료되었으면 `0`을 반환합니다.
- 살아 있는 TTL이 있으면 남은 초를 정수로 반환합니다.

`persist(key)`
- 설정된 TTL을 제거합니다.
- 이를 통해 지연 무효화를 취소할 수 있습니다.

`get_stats()`
- 저장소 상태를 락 안에서 한 번에 읽습니다.
- `size`, `capacity`, `load_factor`, `resize_count`, `expired_removed_count`를 원자적으로 반환합니다.

`_resize(new_capacity)`
- 버킷 수를 늘리고 live entry만 새 버킷 배열에 다시 배치합니다.
- resize 과정에서 이미 만료된 key는 버립니다.

`_record_write()` / `_cleanup_expired_buckets()`
- active expiration의 핵심 로직입니다.
- 쓰기 연산이 일정 횟수 누적되면 일부 버킷만 순회해 expired key를 조금씩 정리합니다.

## 만료 정책과 무효화 방식

현재 저장소는 세 가지 방식으로 데이터를 무효화할 수 있습니다.

- `DEL`: 즉시 무효화
- `EXPIRE`: 일정 시간 뒤 무효화
- `PERSIST`: 설정된 TTL 제거

만료 정책은 기본적으로 lazy expiration입니다. 즉, key를 조회하거나 접근할 때 만료 여부를 확인하고 필요하면 즉시 삭제합니다.

여기에 lightweight active expiration을 추가했습니다. 이 방식은 백그라운드 스레드를 두지 않고, 쓰기 계열 연산이 일정 횟수 누적될 때 일부 버킷만 청소합니다. 따라서 접근되지 않는 expired key도 점진적으로 정리할 수 있습니다.

## 동시성 설계

현재 서버는 멀티스레드 환경에서 저장소에 접근할 수 있으므로, 저장소 내부 상태 보호가 필요합니다.

이를 위해 `HashTableStore`는 전역 `RLock`을 사용합니다.

- `set`
- `get`
- `delete`
- `expire`
- `ttl`
- `persist`
- `get_stats`
- `resize`

위 연산은 모두 같은 락 아래에서 동작합니다. 이 설계는 세밀한 병렬성을 극대화하는 방식은 아니지만, correctness와 구현 단순성 측면에서 현재 프로젝트에 더 적합합니다.

## 서버와의 협업 인터페이스

서버는 저장소 내부 자료구조를 직접 참조하지 않고, `KeyValueStore` 인터페이스만 사용합니다. 이 연결은 [`mini_redis/router.py`](../mini_redis/router.py) 에서 이뤄집니다.

저장소 관련 명령은 아래와 같습니다.

- `SET`
- `GET`
- `DEL`
- `EXPIRE`
- `TTL`
- `PERSIST`
- `INFO`

`INFO`에서는 아래 저장소 통계를 확인할 수 있습니다.

- `keys`
- `capacity`
- `load_factor`
- `resize_count`
- `expired_removed_count`

즉, 저장소는 서버가 바로 붙을 수 있는 독립 모듈로 설계되어 있습니다.

## 테스트

저장소와 관련된 검증은 아래 테스트 파일에 정리되어 있습니다.

- [`tests/test_storage.py`](../tests/test_storage.py)
- [`tests/test_router.py`](../tests/test_router.py)
- [`tests/test_server_integration.py`](../tests/test_server_integration.py)

검증 항목은 다음과 같습니다.

- 해시 충돌 처리
- overwrite
- 없는 key 조회
- 여러 key 삭제 시 삭제 개수 반환
- lazy expiration
- resize 후 데이터 유지
- expired entry 정리
- `TTL`
- `PERSIST`
- active expiration
- 저장소 통계 일관성
- 멀티스레드 접근 시 상태 무결성
- RESP 라우팅과 TCP round trip

테스트 실행:

```bash
python3 -m unittest discover -s tests -v
```

## 정리

이번 작업의 핵심은 “해시 테이블을 하나 구현했다”는 데 있지 않습니다. 더 중요한 점은 Mini Redis 저장소가 실제로 필요한 기능을 식별하고, 그 기능을 Python 환경에 맞는 구조로 다시 설계했다는 점입니다.

현재 저장소는 커스텀 해시 테이블, resize, TTL, lazy expiration, active expiration, 상태 통계, RESP 연동, 동시성 보호를 모두 갖춘 Python형 Mini Redis 저장소입니다.
