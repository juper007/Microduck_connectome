# PM Agent Hiring Plan

Date: 2026-09-15

이 문서는 MicroDuck Connectome 프로젝트를 멀티에이전트 방식으로 실행할 때 PM이 채용할 핵심 역할과 각 역할에 요구할 역량을 정의한다. 기존 `AGENT_ROLES.md`의 세부 책임 16개를 실제 운영에 적합하도록 11개 역할로 묶었다. Safety와 Independent Review는 의도적으로 분리해 자기검증 편향을 줄인다.

## 채용 원칙

- 역할은 전문 분야가 아니라 **명확한 의사결정 권한과 산출물**을 가져야 한다.
- 한 에이전트가 데이터 수집부터 결과 판정까지 독점하지 않게 한다.
- 생물학적 사실, 모델링 가정, 로봇 엔지니어링 매핑을 구분한다.
- Safety는 모든 실험 컨트롤러보다 상위 권한을 갖는다.
- Phase 완료 판정은 구현 담당자가 아니라 Independent Reviewer가 검증한다.

## 1. PM / Systems Architect Agent

**Skill:** `$microduck-pm-architect`

**뽑을 능력**
- robotics/software system architecture
- 복잡한 연구 프로젝트의 WBS/critical path 설계
- interface contract와 dependency 관리
- risk/decision log 관리
- 여러 전문 에이전트의 병렬 작업 조율
- 기술적 trade-off를 일정/위험/검증가능성 기준으로 판단

**주요 책임:** Phase 계획, task routing, architecture decision, gate 준비, cross-agent handoff.

## 2. Connectome & Neurobiology Research Agent

**Skill:** `$connectome-researcher`

**뽑을 능력**
- Drosophila neuroanatomy와 descending/sensory circuits 이해
- MaleCNS/neuPrint 데이터 탐색
- primary literature critical reading
- cell type/body ID/hemisphere annotation 검증
- connectomic inference와 experimentally demonstrated function 구분
- evidence provenance 관리

**주요 책임:** 사용할 neuron population과 pathway가 실제 MaleCNS 및 문헌 근거를 갖는지 검증.

## 3. Connectome Data Engineer Agent

**Skill:** `$connectome-data-engineer`

**뽑을 능력**
- Python data engineering
- `neuprint-python`, dataframe/columnar data, graph processing
- deterministic ETL와 schema validation
- graph serialization/caching
- provenance/version metadata 설계
- 대규모 sparse graph의 효율적 저장/조회

**주요 책임:** MaleCNS 원천 데이터에서 재현 가능한 내부 graph/data layer 구축.

## 4. Neural Runtime Engineer Agent

**Skill:** `$neural-runtime-engineer`

**뽑을 능력**
- computational neuroscience
- LIF/leaky/recurrent network dynamics
- sparse linear algebra
- PyTorch/CUDA/CPU profiling
- numerical stability와 deterministic simulation
- real-time/multi-rate runtime architecture

**주요 책임:** static connectome을 시간에 따라 동작하는 안정적 neural reservoir/runtime으로 구현.

## 5. Perception & Sensory Encoding Agent

**Skill:** `$perception-sensory-encoder`

**뽑을 능력**
- OpenCV/computer vision
- camera geometry, target tracking, optical expansion/looming
- ToF/proximity sensor handling
- signal filtering와 confidence estimation
- perception test fixture 제작
- robot feature를 bounded neural stimulus로 변환하는 설계 능력

**주요 책임:** Camera/ToF 관측을 안정적인 sensory feature와 MaleCNS stimulation으로 변환.

## 6. Behavior & Control Engineer Agent

**Skill:** `$behavior-control-engineer`

**뽑을 능력**
- feedback/control systems
- signal processing, smoothing, hysteresis
- population readout와 linear decoder
- behavior state machine
- velocity/yaw command shaping
- closed-loop oscillation 원인 분석

**주요 책임:** descending-neuron activity를 bounded high-level MicroDuck intent로 변환.

## 7. MicroDuck Simulation & Integration Engineer Agent

**Skill:** `$microduck-integration-engineer`

**뽑을 능력**
- Linux robotics runtime
- MuJoCo
- MicroDuck `robotd`/IPC/JSON-RPC 구조 이해
- 50 Hz real-time-ish loop integration
- official MicroDuck/microduck_rl 코드 추적
- simulator와 physical runtime 차이 분석

**주요 책임:** connectome controller를 공식 MicroDuck 제어 경로와 simulator에 안전하게 연결.

## 8. Robot Safety & Fault-Injection Engineer Agent

**Skill:** `$robot-safety-engineer`

**뽑을 능력**
- robotics fail-safe design
- watchdog/TTL/stale-command handling
- rate/velocity/position limit 설계
- fault injection과 failure-mode analysis
- E-stop 및 hardware test gate 설계
- unsafe change를 거부할 수 있는 독립적 판단

**주요 책임:** experimental controller가 실패해도 robot이 bounded safe state로 가도록 보장.

## 9. Experiment & Evaluation Scientist Agent

**Skill:** `$experiment-evaluation-scientist`

**뽑을 능력**
- hypothesis-driven experiment design
- controls/baselines/ablation 설계
- statistics, confidence intervals, effect size
- randomization와 shared-seed trial design
- robotics performance metrics
- negative/null result를 포함한 과학적 해석

**주요 책임:** “로봇이 움직인다”가 아니라 “실제 connectome topology가 의미 있는가?”를 검증.

## 10. Reproducibility & DevOps Engineer Agent

**Skill:** `$reproducibility-devops-engineer`

**뽑을 능력**
- Python environment/package management
- CI/CD와 automated tests
- dependency/data/version pinning
- experiment configuration/versioning
- structured telemetry/artifact management
- clean-machine reproduction

**주요 책임:** commit + config + seed만으로 실험과 결과를 재현 가능하게 유지.

## 11. Independent Phase Reviewer Agent

**Skill:** `$independent-phase-reviewer`

**뽑을 능력**
- defect-first code review
- scientific-method review
- robotics safety review
- clean-checkout reproduction
- evidence-based Definition of Done 판정
- 구현팀의 가정과 성공 주장에 독립적으로 이의를 제기하는 능력

**주요 책임:** 각 Phase gate를 독립 검증하고 PASS/FAIL/BLOCKED를 판정.

## 운영 모델

```text
                    PM / Systems Architect
                           │
          ┌────────────────┼────────────────┐
          │                │                │
 Connectome/Data      Neural/Perception   Robot/Control
          │                │                │
          └──────────────┬─┴─┬──────────────┘
                         │   │
                    Experiment Safety
                         │   │
                         └─┬─┘
                    Reproducibility
                           │
                  Independent Reviewer
```

### 권장 task flow

1. PM이 `TASK_BREAKDOWN.md`의 task를 선택하고 acceptance criterion을 확인한다.
2. Research/Data agent가 biological/data input을 고정한다.
3. Runtime/Perception/Control/Integration agent가 필요한 구현을 병렬 진행한다.
4. Safety agent가 failure path를 검증한다.
5. DevOps agent가 실행과 artifact를 재현 가능하게 만든다.
6. Experiment agent가 pre-defined metric으로 평가한다.
7. Independent Reviewer가 `COMPLETION_CRITERIA.md` 기준으로 gate를 판정한다.

## Codex skill 위치

모든 역할 스킬은 repo-scoped discovery를 위해 다음 위치에 저장한다.

```text
.agents/skills/<skill-name>/SKILL.md
```

루트 `AGENTS.md`에는 어떤 작업에서 어떤 스킬을 사용해야 하는지 routing rule을 둔다.
