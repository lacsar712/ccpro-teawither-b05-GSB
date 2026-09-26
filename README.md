# TeaWither-01 · 茶萎凋台账

Django 5 + PostgreSQL 服务端渲染应用：Templates + HTMX + 自定义 CSS，无 Vue/React SPA。

## 技术栈

- Django 5、PostgreSQL
- Session 登录
- HTMX（CDN）局部刷新列表
- Docker Compose：`web` + `db`

## 端口与数据库

| 服务 | 端口 |
|------|------|
| Web  | **4100** |
| Postgres | **5440**（容器内 5432） |

数据库账号：`teawither` / `teawither` / 库名 `teawither`

## 快速启动

```bash
cd TeaWither/TeaWither-01
docker compose up --build -d
```

浏览器打开：http://localhost:4100

演示账号：

- `admin` / `123456`（超级用户）
- `witherer` / `123456`（普通用户）

容器启动时会自动：`migrate` → `seed_data` → `collectstatic` → `gunicorn`

## 本地开发（可选）

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
# 确保本机 Postgres 监听 5440，或先 docker compose up -d db
set POSTGRES_HOST=localhost
set POSTGRES_PORT=5440
python manage.py migrate
python manage.py seed_data
python manage.py runserver 0.0.0.0:4100
```

## 业务模型

1. **Garden（茶园）**：`name`、`altitudeBand`、`notes`
2. **Trough（萎凋槽）**：归属茶园、`troughCode`、`cultivar`、`loadKg`、状态 `loading|withering|ready`、允许窗 `windowStart` / `windowEnd`；同一茶园内槽位编号唯一
3. **WitherBatch（萎凋批次）**：归属槽位、`startedAt`、`targetMoisture`、`actualMoisture`（可空）、`rollGrade`

### 业务规则

**槽位状态规则**：将槽位状态设为 `ready`（可下槽）时，若最新批次的 `actualMoisture` 为空或大于 40，抛出中文 `ValidationError`。

**允许窗**：每个槽位可配置允许窗 `[windowStart, windowEnd]`（闭区间，均为可空，空表示该侧不限制；允许窗起必须早于允许窗止）。批次开始时刻 `startedAt` 必须落在所属槽允许窗内，**新建和更新都校验**，越窗即拒绝。

**状态联锁（仅新建受限）**：

| 槽位状态 | 新建批次 |
|---|---|
| 装叶中（loading） | **禁止** |
| 萎凋中（withering） | 允许 |
| 可下槽（ready） | 允许 |

更新批次（如在可下槽上补录/修改实测含水率）不受槽位状态限制，但只要改开始时刻，仍受允许窗与防乱序约束。

**防乱序（新建、更新都拦）**：

- **乱序定义**：同一槽位内，批次的录入顺序（数据库 `id` 升序，即先记账者在前）与开始时刻顺序（`startedAt` 降序，即时间晚者在前）必须一致。换言之，**后录入的批次开始时刻不得晚于先录入的批次**——只允许按时间向前补录更早的批次。开始时刻相同则以 `id` 次序打破并列，仍可对账。
- 新建：同槽若已有开始时刻更早的批次，新批次开始不得晚于槽内任一批次（更准确说：不得晚于槽内最早的开始时刻；与任一批次相同允许），违者拒绝。
- 更新：不得把开始时刻改到同槽**其它批次**之后（也不得改到其它批次之前而越过下一条）——即以录入顺序中相邻的批次为界，开始时刻只能停留在相邻批次之间，违者拒绝。只改实测含水率等其它字段时开始时刻未动，自然通过。
- 批次列表支持按槽位过滤（`?trough=<id>`），并统一按开始时刻降序（`-startedAt, -id`）排序；过滤到单槽后，行顺序即对账顺序。

校验集中在模型层 `WitherBatch.clean()` / `Trough.clean()`，`save()` 调 `full_clean()`，表单与后台共用同一套中文错误信息。

## 种子数据

```bash
python manage.py seed_data
```

幂等：已有茶园则只保证账号存在。亦可在环境变量 `TEAWITHER_AUTO_SEED=1` 时于 `post_migrate` 自动播种。种子包含一个**一槽多批次**的槽位（A-01 上有两条按规则向前补录的批次，均在允许窗内）。

## 目录结构

```
TeaWither-01/
  manage.py
  requirements.txt
  Dockerfile
  entrypoint.sh
  docker-compose.yml
  config/           # 项目配置
  apps/gardens/     # 模型、视图、种子命令
  templates/        # Django 模板
  static/css/       # 自定义样式（茶绿色顶栏）
```
