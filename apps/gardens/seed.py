from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import Garden, Trough, WitherBatch


def ensure_seed_data():
    """Idempotent seed: users + sample gardens/troughs/batches."""
    User = get_user_model()

    if not User.objects.filter(username="admin").exists():
        User.objects.create_superuser("admin", "admin@teawither.local", "123456")

    if not User.objects.filter(username="witherer").exists():
        User.objects.create_user("witherer", "witherer@teawither.local", "123456")

    if Garden.objects.exists():
        return

    now = timezone.now().replace(second=0, microsecond=0)
    window_start = now - timezone.timedelta(days=3)
    window_end = now + timezone.timedelta(days=1)

    g1 = Garden.objects.create(
        name="云雾岭一号园",
        altitudeBand="800-1000m",
        notes="向阳坡，晨雾较重",
    )
    g2 = Garden.objects.create(
        name="竹影台二号园",
        altitudeBand="600-800m",
        notes="背风缓坡",
    )

    t1 = Trough.objects.create(
        garden=g1,
        troughCode="A-01",
        cultivar="福鼎大白",
        loadKg=Decimal("120.50"),
        status=Trough.STATUS_WITHERING,
        windowStart=window_start,
        windowEnd=window_end,
    )
    # 一槽多批次：同一槽内按开始时刻先后依次创建，创建顺序与开始时刻一致（不乱序）
    WitherBatch.objects.create(
        trough=t1,
        startedAt=now - timezone.timedelta(hours=48),
        targetMoisture=Decimal("39.50"),
        actualMoisture=Decimal("39.10"),
        rollGrade="三级",
    )
    WitherBatch.objects.create(
        trough=t1,
        startedAt=now - timezone.timedelta(hours=30),
        targetMoisture=Decimal("38.50"),
        actualMoisture=Decimal("38.20"),
        rollGrade="二级",
    )
    WitherBatch.objects.create(
        trough=t1,
        startedAt=now - timezone.timedelta(hours=18),
        targetMoisture=Decimal("38.00"),
        actualMoisture=Decimal("37.50"),
        rollGrade="一级",
    )

    # 装叶中的槽：批次在萎凋状态下登记后，槽再转回装叶（新建联锁只约束创建时刻）
    t2 = Trough.objects.create(
        garden=g1,
        troughCode="A-02",
        cultivar="铁观音",
        loadKg=Decimal("95.00"),
        status=Trough.STATUS_WITHERING,
        windowStart=window_start,
        windowEnd=window_end,
    )
    WitherBatch.objects.create(
        trough=t2,
        startedAt=now - timezone.timedelta(hours=2),
        targetMoisture=Decimal("40.00"),
        actualMoisture=None,
        rollGrade="待评",
    )
    t2.status = Trough.STATUS_LOADING
    t2.save()

    t3 = Trough.objects.create(
        garden=g2,
        troughCode="B-01",
        cultivar="黄金芽",
        loadKg=Decimal("88.25"),
        status=Trough.STATUS_WITHERING,
        windowStart=window_start,
        windowEnd=window_end,
    )
    WitherBatch.objects.create(
        trough=t3,
        startedAt=now - timezone.timedelta(hours=30),
        targetMoisture=Decimal("36.00"),
        actualMoisture=Decimal("42.00"),
        rollGrade="二级",
    )

    # Ready trough with valid moisture
    t4 = Trough.objects.create(
        garden=g2,
        troughCode="B-02",
        cultivar="龙井43",
        loadKg=Decimal("110.00"),
        status=Trough.STATUS_WITHERING,
        windowStart=window_start,
        windowEnd=window_end,
    )
    WitherBatch.objects.create(
        trough=t4,
        startedAt=now - timezone.timedelta(hours=24),
        targetMoisture=Decimal("35.00"),
        actualMoisture=Decimal("34.80"),
        rollGrade="特级",
    )
    t4.status = Trough.STATUS_READY
    t4.save()
