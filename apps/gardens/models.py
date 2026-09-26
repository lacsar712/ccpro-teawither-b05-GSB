from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Garden(models.Model):
    name = models.CharField("茶园名称", max_length=120)
    altitudeBand = models.CharField("海拔带", max_length=60)
    notes = models.TextField("备注", blank=True, default="")

    class Meta:
        ordering = ["name"]
        verbose_name = "茶园"
        verbose_name_plural = "茶园"

    def __str__(self):
        return self.name


class Trough(models.Model):
    STATUS_LOADING = "loading"
    STATUS_WITHERING = "withering"
    STATUS_READY = "ready"
    STATUS_CHOICES = [
        (STATUS_LOADING, "装叶中"),
        (STATUS_WITHERING, "萎凋中"),
        (STATUS_READY, "可下槽"),
    ]

    garden = models.ForeignKey(
        Garden,
        on_delete=models.CASCADE,
        related_name="troughs",
        verbose_name="茶园",
    )
    troughCode = models.CharField("槽位编号", max_length=40)
    cultivar = models.CharField("茶树品种", max_length=80)
    loadKg = models.DecimalField("装叶量(kg)", max_digits=10, decimal_places=2)
    status = models.CharField(
        "状态",
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_LOADING,
    )
    windowStart = models.DateTimeField(
        "允许窗起",
        null=True,
        blank=True,
        help_text="批次开始时刻允许的最早时间；留空表示不限制",
    )
    windowEnd = models.DateTimeField(
        "允许窗止",
        null=True,
        blank=True,
        help_text="批次开始时刻允许的最晚时间；留空表示不限制",
    )

    class Meta:
        ordering = ["garden__name", "troughCode"]
        verbose_name = "萎凋槽"
        verbose_name_plural = "萎凋槽"
        constraints = [
            models.UniqueConstraint(
                fields=["garden", "troughCode"],
                name="uniq_trough_code_per_garden",
            ),
        ]

    def __str__(self):
        return f"{self.garden.name}-{self.troughCode}"

    def latest_batch(self):
        return self.batches.order_by("-startedAt", "-id").first()

    def window_contains(self, when):
        """开始时刻是否落在本槽允许窗内（闭区间；空边界视为不限制）。"""
        if self.windowStart is not None and when < self.windowStart:
            return False
        if self.windowEnd is not None and when > self.windowEnd:
            return False
        return True

    def clean(self):
        super().clean()
        errors = {}
        if (
            self.windowStart is not None
            and self.windowEnd is not None
            and self.windowStart >= self.windowEnd
        ):
            errors["windowStart"] = "允许窗起必须早于允许窗止。"
        if self.status == self.STATUS_READY:
            latest = None
            if self.pk:
                latest = (
                    WitherBatch.objects.filter(trough_id=self.pk)
                    .order_by("-startedAt", "-id")
                    .first()
                )
            if (
                latest is None
                or latest.actualMoisture is None
                or latest.actualMoisture > 40
            ):
                errors["status"] = "无法设为可下槽：最新萎凋批次的实测含水率为空或高于 40%。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class WitherBatch(models.Model):
    trough = models.ForeignKey(
        Trough,
        on_delete=models.CASCADE,
        related_name="batches",
        verbose_name="萎凋槽",
    )
    startedAt = models.DateTimeField("开始时间")
    targetMoisture = models.DecimalField(
        "目标含水率(%)", max_digits=5, decimal_places=2
    )
    actualMoisture = models.DecimalField(
        "实测含水率(%)",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    rollGrade = models.CharField("揉捻等级", max_length=40)

    class Meta:
        ordering = ["-startedAt", "-id"]
        verbose_name = "萎凋批次"
        verbose_name_plural = "萎凋批次"

    def __str__(self):
        return f"{self.trough} @ {self.startedAt:%Y-%m-%d %H:%M}"

    def clean(self):
        super().clean()
        errors = {}
        trough = self.trough

        # 1) 开始时刻必须落在所属槽允许窗内（新建、更新均校验）
        if trough is not None and self.startedAt is not None:
            if not trough.window_contains(self.startedAt):
                start = (
                    timezone.localtime(trough.windowStart).strftime("%Y-%m-%d %H:%M")
                    if trough.windowStart
                    else "不限"
                )
                end = (
                    timezone.localtime(trough.windowEnd).strftime("%Y-%m-%d %H:%M")
                    if trough.windowEnd
                    else "不限"
                )
                errors["startedAt"] = (
                    f"开始时刻必须落在槽位「{trough}」允许窗 [{start}, {end}] 内。"
                )

        # 2) 与槽当前状态联锁：仅新建受限；装叶中禁止新建批次，
        #    萎凋中 / 可下槽可建。更新（含可下槽上补实测）一律放行。
        if self.pk is None and trough is not None:
            if trough.status == Trough.STATUS_LOADING:
                errors["trough"] = (
                    f"槽位「{trough}」处于装叶中，禁止新建萎凋批次；"
                    "待状态为萎凋中或可下槽后再建。"
                )

        # 3) 防乱序：同一槽内，录入顺序（id 升序）必须与开始时刻降序一致，
        #    即先录入的批次开始时刻不早于后录入的批次，二者顺序一致方可对账。
        if trough is not None and trough.pk and self.startedAt is not None:
            siblings = WitherBatch.objects.filter(trough=trough)
            if self.pk is not None:
                siblings = siblings.exclude(pk=self.pk)
                # 更新：不得越过同槽相邻录入批次——不得晚于上一条，
                # 也不得早于下一条；只改实测含水率等其它字段不受影响。
                predecessor = siblings.filter(pk__lt=self.pk).order_by("-pk").first()
                if (
                    predecessor is not None
                    and self.startedAt > predecessor.startedAt
                ):
                    errors.setdefault(
                        "startedAt",
                        "开始时刻不得晚于同槽上一条录入批次"
                        f"（{timezone.localtime(predecessor.startedAt):%Y-%m-%d %H:%M}），"
                        "以免与录入顺序乱序。",
                    )
                successor = siblings.filter(pk__gt=self.pk).order_by("pk").first()
                if (
                    successor is not None
                    and self.startedAt < successor.startedAt
                ):
                    errors.setdefault(
                        "startedAt",
                        "开始时刻不得早于同槽下一条录入批次"
                        f"（{timezone.localtime(successor.startedAt):%Y-%m-%d %H:%M}），"
                        "以免与录入顺序乱序。",
                    )
            else:
                # 新建：同槽若已有批次，新批次开始不得晚于任一批次
                # （允许并列，列表以 id 次序打破并列）。
                later = siblings.order_by("startedAt", "id").first()
                if later is not None and self.startedAt > later.startedAt:
                    errors.setdefault(
                        "startedAt",
                        "同一槽已存在开始时刻为"
                        f" {timezone.localtime(later.startedAt):%Y-%m-%d %H:%M} 的批次，"
                        "新批次开始时刻不得晚于它（只能按时间向前补录，禁止乱序）。",
                    )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
