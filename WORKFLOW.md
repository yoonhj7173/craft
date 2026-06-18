# Development Workflow — pondas.ai

로컬에서 작업 → PR → CI(regression) 통과 → 머지 → 자동 prod 배포.
`main`은 보호 브랜치라 **직접 푸시 불가**. 모든 변경은 PR을 거친다.

---

## 환경 (3개 DB, 완전 분리)

| 환경 | DB | 용도 |
|---|---|---|
| **로컬 dev** | `localhost:5432/cursorpm` (`backend/.env`) | 개발/수동 테스트 |
| **CI** | GitHub Actions 일회용 Postgres | PR 자동 테스트 (매번 폐기) |
| **prod** | Railway Postgres 플러그인 | 라이브 (`pondas.ai`) |

로컬 작업은 prod DB를 절대 건드리지 않는다.

---

## 흐름

```
1. feature 브랜치 생성     git checkout -b feat/<name>
2. 로컬에서 작업 + 검증     (build / pytest / 직접 동작 확인)
3. 커밋 + 푸시             git push -u origin feat/<name>
4. PR 오픈                 gh pr create
5. CI 자동 실행            backend(pytest) + frontend(build)  ← regression
6. 🟢 통과 + 승인 → 머지    gh pr merge --squash
7. main 머지 → 자동 배포    Railway(api) + Vercel(web)가 main을 감지해 prod 반영
```

**승인 = PR 머지**가 prod 배포 트리거다. CI 빨간불이면 머지 버튼이 잠긴다.

---

## 브랜치 보호 규칙 (main)

- PR 필수 (직접 푸시 차단)
- 필수 통과 체크: `backend (pytest)`, `frontend (build)`
- `strict`: 머지 전 main 최신화 강제
- linear history, force-push/삭제 금지
- `enforce_admins: false` — admin 비상 우회 가능 (핫픽스용)

규칙 변경:
```bash
gh api repos/yoonhj7173/pondas.ai/branches/main/protection   # 현재 확인
```

---

## 배포

- **Railway** (`api.pondas.ai`, worker): main 푸시 → 자동 빌드/배포. `start-web.sh`가 `alembic upgrade head` + `seed.py` 실행 후 uvicorn.
- **Vercel** (`pondas.ai`): main 푸시 → 자동 배포. PR 브랜치는 **preview 배포**(라이브 영향 없음)로 미리 확인 가능.
- 마이그레이션은 web 서비스 기동 시 자동. prod DB 스키마 변경은 PR에 alembic 리비전을 포함시킬 것.

## 핫픽스 (비상)

`enforce_admins: false`라 admin은 main 직접 푸시 가능하지만, **원칙적으로 핫픽스도 PR로.** 정말 급할 때만 직접 푸시하고, 사후에 CI 결과 확인.
