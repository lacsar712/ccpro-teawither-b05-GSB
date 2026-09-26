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
2. **Trough（萎凋槽）**：归属茶园、`troughCode`、`cultivar`、`loadKg`、状态 `loading|withering|ready`、允许窗 `windowStart`~`windowEnd`；同一茶园内槽位编号唯一
3. **WitherBatch（萎凋批次）**：归属槽位、`startedAt`、`targetMoisture`、`actualMoisture`（可空）、`rollGrade`

**业务规则**：

1. 将槽位状态设为 `ready`（可下槽）时，若最新批次的 `actualMoisture` 为空或大于 40，抛出中文 `ValidationError`。
2. **允许窗**：新建或更新批次时，`startedAt` 必须落在所属槽允许窗 `[windowStart, windowEnd]` 内（含边界），否则拒绝。
3. **状态联锁（仅新建）**：`loading`（装叶中）的槽禁止新建批次；`withering`（萎凋中）与 `ready`（可下槽）可建。更新批次不校验槽状态——可下槽上更新实测含水率仍允许，但改开始时刻仍受允许窗与乱序约束。
4. **乱序定义**：同一槽位内，批次的创建先后（`id` 升序）必须与开始时刻先后一致；若批次 A 比批次 B 先创建（`id` 更小）但 A 的开始时刻更晚，即为**乱序**。为防止乱序：
   - 新建：新批次 `id` 最大，其开始时刻不得早于槽内现有最晚开始时刻（槽内已存在开始时刻更晚的批次时拒绝）。
   - 更新：不得把开始时刻改到更早创建批次之前，或更晚创建批次之后。
5. **列表对账**：批次列表始终按开始时刻倒序（`-startedAt, -id`），支持 `?trough=<id>` 按槽过滤；满足不乱序约束时，过滤后的顺序与创建顺序一致，可对账。

## 种子数据

```bash
python manage.py seed_data
```

幂等：已有茶园则只保证账号存在。亦可在环境变量 `TEAWITHER_AUTO_SEED=1` 时于 `post_migrate` 自动播种。

样例数据覆盖全部槽状态，其中 `A-01` 为一槽多批次（3 个批次，创建顺序与开始时刻一致），所有批次开始时刻均落在所属槽允许窗内。

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
