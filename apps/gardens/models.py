from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Max, Min
from django.utils import timezone


def _fmt(dt):
    return timezone.localtime(dt).strftime("%Y-%m-%d %H:%M")


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
    windowStart = models.DateTimeField("允许窗开始")
    windowEnd = models.DateTimeField("允许窗结束")

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

    def clean(self):
        super().clean()
        if (
            self.windowStart is not None
            and self.windowEnd is not None
            and self.windowStart >= self.windowEnd
        ):
            raise ValidationError(
                {"windowEnd": "允许窗结束时刻必须晚于允许窗开始时刻。"}
            )
        if self.status != self.STATUS_READY:
            return
        latest = None
        if self.pk:
            latest = (
                WitherBatch.objects.filter(trough_id=self.pk)
                .order_by("-startedAt", "-id")
                .first()
            )
        if latest is None or latest.actualMoisture is None or latest.actualMoisture > 40:
            raise ValidationError(
                {
                    "status": "无法设为可下槽：最新萎凋批次的实测含水率为空或高于 40%。"
                }
            )

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
        if self.trough_id is None or self.startedAt is None:
            return
        trough = self.trough
        started = self.startedAt

        # 1) 开始时刻必须落在所属槽允许窗内（新建与更新均校验）
        if trough.windowStart is not None and started < trough.windowStart:
            raise ValidationError(
                {
                    "startedAt": f"开始时刻早于所属槽允许窗开始（{_fmt(trough.windowStart)}）。"
                }
            )
        if trough.windowEnd is not None and started > trough.windowEnd:
            raise ValidationError(
                {
                    "startedAt": f"开始时刻晚于所属槽允许窗结束（{_fmt(trough.windowEnd)}）。"
                }
            )

        # 2) 状态联锁：仅新建时校验，装叶中禁止建批；萎凋中/可下槽可建。
        #    更新不校验状态（可下槽上更新实测含水率仍允许）。
        if self.pk is None and trough.status == Trough.STATUS_LOADING:
            raise ValidationError(
                {"trough": "装叶中的萎凋槽禁止新建批次（须为萎凋中或可下槽）。"}
            )

        # 3) 防乱序：同一槽内，批次创建先后（id 升序）须与开始时刻先后一致。
        #    新建批次 id 最大，故开始时刻不得早于槽内现有最晚开始时刻；
        #    更新不得把开始时刻改到更早创建批次之前，或更晚创建批次之后。
        siblings = WitherBatch.objects.filter(trough_id=trough.pk)
        if self.pk is None:
            latest_start = siblings.aggregate(m=Max("startedAt"))["m"]
            if latest_start is not None and started < latest_start:
                raise ValidationError(
                    {
                        "startedAt": (
                            f"该槽已存在开始时刻更晚的批次（最晚 {_fmt(latest_start)}），"
                            "新批次开始时刻不得早于该时刻，以免乱序。"
                        )
                    }
                )
        else:
            siblings = siblings.exclude(pk=self.pk)
            earlier_max = siblings.filter(id__lt=self.pk).aggregate(
                m=Max("startedAt")
            )["m"]
            later_min = siblings.filter(id__gt=self.pk).aggregate(
                m=Min("startedAt")
            )["m"]
            if earlier_max is not None and started < earlier_max:
                raise ValidationError(
                    {
                        "startedAt": (
                            "不得把开始时刻改到本槽更早创建的批次"
                            f"（{_fmt(earlier_max)}）之前，以免乱序。"
                        )
                    }
                )
            if later_min is not None and started > later_min:
                raise ValidationError(
                    {
                        "startedAt": (
                            "不得把开始时刻改到本槽更晚创建的批次"
                            f"（{_fmt(later_min)}）之后，以免乱序。"
                        )
                    }
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
