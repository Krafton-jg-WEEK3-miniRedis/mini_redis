# Mini Redis

TCP 기반 Mini Redis 서버 실험 프로젝트입니다. 현재 저장소에는 RESP2 요청 파싱, 명령 라우팅, 해시테이블 기반 저장소, 서버 통합 테스트가 포함되어 있습니다.

## 지원 명령

- `PING`
- `ECHO`
- `SET`
- `GET`
- `DEL`
- `EXPIRE`
- `INFO`
- `QUIT`
- `EXIT`
- `COMMAND`
- `CLIENT SETINFO`
- `HELLO`

## 실행

```bash
python3 main.py --host 127.0.0.1 --port 6379
```

## 테스트

```bash
python3 -m unittest discover -s tests -v
```

## 구조

- `mini_redis/resp.py`: RESP2 요청 파싱과 응답 직렬화
- `mini_redis/router.py`: 명령 디스패치와 응답 결정
- `mini_redis/storage.py`: 저장소 인터페이스와 해시테이블 엔진
- `mini_redis/server.py`: TCP 서버와 커넥션 루프

## 다음 통합 포인트

- 4번 팀원의 해시테이블 저장소를 더 큰 명령 집합과 연결
- 2번 팀원의 CLI와 연동해 명령 round trip 검증
- 1번 팀원의 데모 웹에서 MongoDB 대비 응답시간 비교
