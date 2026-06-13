"""Pydantic request/response schemas.

v1의 cluster/unit/map 스키마는 v3 전환(item 5)에서 제거했다. v3 스키마(projects,
teams, agents, edges, map, tasks, outputs 등)는 각 라우터를 추가하는 item 6–13에서
해당 라우터 옆에 정의/추가한다. 지금은 의도적으로 비어 있다.
"""

from __future__ import annotations
