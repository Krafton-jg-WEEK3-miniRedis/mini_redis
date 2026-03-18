# 팀원3 서버/라우터 작업 정리

이 문서는 3번 팀원이 담당한 Mini Redis 서버/라우터 영역의 구현 내용, 현재 상태, 테스트 범위, 남은 개선사항을 정리한 문서입니다.

## 담당 범위

기획서 기준 3번 팀원의 기본 역할은 다음과 같습니다.

- TCP 기반 Mini Redis 서버 구현
- RESP2 요청 파싱
- 명령 라우팅과 에러 응답 처리
- 저장소와 연결되는 인터페이스 계층 정리
- `PING`, `SET`, `GET`, `DEL`, `INFO`, `QUIT`, `EXIT` 지원

실제 구현 과정에서는 CLI와 저장소 확장에 맞춰 아래 명령도 함께 연동했습니다.

- `ECHO`
- `EXPIRE`
- `TTL`
- `PERSIST`
- `COMMAND`
- `CLIENT SETINFO`
- `HELLO`

## 구현 결과

현재 서버/라우터는 아래 구조로 분리돼 있습니다.

- [`mini_redis/server.py`](../mini_redis/server.py): TCP 서버, 연결 수락, 요청 루프
- [`mini_redis/router.py`](../mini_redis/router.py): 명령 디스패치, 인자 검증, 에러 응답
- [`mini_redis/resp.py`](../mini_redis/resp.py): RESP2 요청 파싱과 응답 직렬화

핵심적으로 정리된 내용은 다음과 같습니다.

- 서버와 라우터, RESP 처리 책임을 파일 단위로 분리했습니다.
- 종료 명령은 `QUIT`, `EXIT`를 모두 지원하도록 유지했습니다.
- 저장소는 `KeyValueStore` 프로토콜을 통해 연결되도록 정리했습니다.
- 잘못된 RESP 입력, 인자 수 오류, 알 수 없는 명령에 대한 에러 응답을 추가했습니다.
- `CLIENT`, `HELLO`, `INFO`의 인자 검증 규칙을 정리했습니다.
- RESP 파서를 보강해 null bulk, 잘못된 길이, 중간 EOF 같은 경계 입력을 명시적으로 거절하도록 했습니다.

## 현재 서버 동작

현재 기준 동작 요약:

- 프로토콜은 RESP2 기준으로 유지합니다.
- `HELLO`는 인자 없이 호출하거나 `HELLO 2`만 허용합니다.
- `INFO`는 전체 정보 또는 `server`, `stats`, `store` 섹션 조회를 지원합니다.
- `TTL`, `PERSIST`는 저장소 만료 상태 제어용 명령으로 지원합니다.
- `CLIENT SETINFO <LIB-NAME|LIB-VER> <value>` 형식만 허용합니다.

## 테스트 범위

서버/라우터 영역에서 현재 검증하는 테스트는 다음과 같습니다.

- [`tests/test_router.py`](../tests/test_router.py)
  - 명령 라우팅
  - 인자 수 오류
  - `CLIENT`, `HELLO`, `INFO` 보조 명령 처리
  - `EXPIRE`, `TTL`, `PERSIST` 동작
- [`tests/test_server_integration.py`](../tests/test_server_integration.py)
  - TCP round trip
  - 잘못된 RESP 입력
  - null bulk, truncated bulk data 같은 경계 입력
  - `QUIT`/`EXIT` 종료 처리
- [`tests/test_resp.py`](../tests/test_resp.py)
  - RESP 파서 단위 테스트
  - multibulk 길이 오류
  - bulk length 오류
  - null bulk string 거절
  - 중간 EOF 처리

최근 기준 전체 테스트는 `python3 -m unittest discover -s tests -v`로 통과한 상태입니다.

## 협업 관점에서 정리된 점

- 서버는 저장소 내부 구현을 직접 알지 않고 `KeyValueStore` 인터페이스만 사용합니다.
- CLI는 서버 명령을 직접 구현하지 않고 RESP2 형식으로 요청을 보내는 역할에 집중합니다.
- README와 CLI 도움말은 현재 서버 지원 범위와 일치하도록 정리했습니다.

## 변경 파일 요약

3번 팀원 작업과 직접 관련된 주요 파일은 아래입니다.

- [`mini_redis/server.py`](../mini_redis/server.py)
- [`mini_redis/router.py`](../mini_redis/router.py)
- [`mini_redis/resp.py`](../mini_redis/resp.py)
- [`mini_redis/cli.py`](../mini_redis/cli.py)
- [`tests/test_router.py`](../tests/test_router.py)
- [`tests/test_server_integration.py`](../tests/test_server_integration.py)
- [`tests/test_resp.py`](../tests/test_resp.py)
- [`README.md`](../README.md)

## 남은 개선사항

현재 기준으로 남아 있는 개선사항은 아래 정도입니다.

- RESP2만 사용할 계획이라면 inline command 입력 허용 여부를 정책적으로 정리할 필요가 있습니다.
  - 현재 `RespReader`는 RESP array가 아닌 공백 분리 입력도 허용합니다.
- CLI 응답 파서도 서버 요청 파서 수준으로 경계 검증을 더 강화할 수 있습니다.
  - malformed reply, 잘린 array reply 같은 경우를 더 엄격히 처리할 여지가 있습니다.
- 서버 생성 책임을 더 분리할 수 있습니다.
  - 현재는 서버가 기본 저장소 구현체를 직접 생성합니다.
- 통합 관점의 후속 작업은 여전히 남아 있습니다.
  - 2번 팀원 CLI와 실제 사용 흐름 검증 강화
  - 1번 팀원 데모 웹과의 비교 시나리오 연결
  - 4번 팀원 저장소 확장과 더 넓은 명령 집합의 결합

## 정리

3번 팀원 영역은 현재 Mini Redis의 서버 진입점, RESP2 파서, 명령 라우팅, 에러 처리, 저장소 연동 경계를 갖춘 상태입니다. 기본 명령 처리뿐 아니라 만료 명령, 상태 조회, 보조 명령, 입력 경계 오류까지 포함해 서버 품질을 높이는 방향으로 정리되었습니다.
