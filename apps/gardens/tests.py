from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Garden, Trough, WitherBatch


class TroughWindowTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.garden = Garden.objects.create(name="测试园", altitudeBand="600m")

    def make_trough(self, status=Trough.STATUS_WITHERING, start=None, end=None):
        return Trough.objects.create(
            garden=self.garden,
            troughCode=f"T-{Trough.objects.count() + 1}",
            cultivar="福鼎大白",
            loadKg=Decimal("100.00"),
            status=status,
            windowStart=start,
            windowEnd=end,
        )

    def test_window_bounds_create(self):
        t = self.make_trough(
            start=self.now - timezone.timedelta(hours=12),
            end=self.now + timezone.timedelta(hours=12),
        )

        def make_at(dt):
            return WitherBatch(
                trough=t,
                startedAt=dt,
                targetMoisture=Decimal("38.00"),
                rollGrade="一级",
            )

        make_at(self.now).full_clean()  # 窗内通过
        make_at(self.now - timezone.timedelta(hours=12)).full_clean()  # 边界（闭区间）
        with self.assertRaises(ValidationError) as ctx:
            make_at(self.now - timezone.timedelta(hours=13)).full_clean()
        self.assertIn("startedAt", ctx.exception.message_dict)
        with self.assertRaises(ValidationError):
            make_at(self.now + timezone.timedelta(hours=13)).full_clean()

    def test_null_window_means_unbounded(self):
        t = self.make_trough()
        WitherBatch(
            trough=t,
            startedAt=self.now - timezone.timedelta(days=400),
            targetMoisture=Decimal("38.00"),
            rollGrade="一级",
        ).full_clean()

    def test_window_start_must_precede_end(self):
        t = Trough(
            garden=self.garden,
            troughCode="T-bad",
            cultivar="福鼎大白",
            loadKg=Decimal("100.00"),
            status=Trough.STATUS_WITHERING,
            windowStart=self.now,
            windowEnd=self.now - timezone.timedelta(hours=1),
        )
        with self.assertRaises(ValidationError) as ctx:
            t.full_clean()
        self.assertIn("windowStart", ctx.exception.message_dict)

    def test_update_moving_outside_window_rejected(self):
        t = self.make_trough(
            start=self.now - timezone.timedelta(hours=12),
            end=self.now + timezone.timedelta(hours=12),
        )
        b = WitherBatch.objects.create(
            trough=t,
            startedAt=self.now,
            targetMoisture=Decimal("38.00"),
            rollGrade="一级",
        )
        b.startedAt = self.now + timezone.timedelta(hours=13)
        with self.assertRaises(ValidationError):
            b.full_clean()
        # 窗内改时间允许
        b.startedAt = self.now - timezone.timedelta(hours=1)
        b.full_clean()


class StatusInterlockTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.garden = Garden.objects.create(name="测试园", altitudeBand="600m")

    def make_trough(self, status):
        t = Trough.objects.create(
            garden=self.garden,
            troughCode=f"T-{Trough.objects.count() + 1}",
            cultivar="福鼎大白",
            loadKg=Decimal("100.00"),
            status=(
                Trough.STATUS_WITHERING
                if status == Trough.STATUS_READY
                else status
            ),
        )
        if status == Trough.STATUS_READY:
            WitherBatch.objects.create(
                trough=t,
                startedAt=self.now - timezone.timedelta(hours=4),
                targetMoisture=Decimal("35.00"),
                actualMoisture=Decimal("34.90"),
                rollGrade="特级",
            )
            t.status = Trough.STATUS_READY
            t.save()
        return t

    def make_batch(self, t, started_at=None):
        return WitherBatch(
            trough=t,
            startedAt=started_at or self.now,
            targetMoisture=Decimal("38.00"),
            rollGrade="一级",
        )

    def test_loading_blocks_create(self):
        t = self.make_trough(Trough.STATUS_LOADING)
        with self.assertRaises(ValidationError) as ctx:
            self.make_batch(t).full_clean()
        self.assertIn("trough", ctx.exception.message_dict)

    def test_withering_and_ready_allow_create(self):
        # 萎凋中空槽可直接建批
        t = self.make_trough(Trough.STATUS_WITHERING)
        self.make_batch(
            t, started_at=self.now - timezone.timedelta(hours=1)
        ).full_clean()
        # 可下槽槽已有 -4h 的批次，新批次按规则向前补录（更早）应放行
        ready = self.make_trough(Trough.STATUS_READY)
        self.make_batch(
            ready, started_at=self.now - timezone.timedelta(hours=8)
        ).full_clean()

    def test_update_allowed_even_on_loading_or_ready(self):
        # 先在萎凋中建批，再把槽改回装叶中（更新历史批次不应被拦）
        t = self.make_trough(Trough.STATUS_WITHERING)
        b = WitherBatch.objects.create(
            trough=t,
            startedAt=self.now - timezone.timedelta(hours=2),
            targetMoisture=Decimal("40.00"),
            rollGrade="待评",
        )
        t.status = Trough.STATUS_LOADING
        t.save()
        b.actualMoisture = Decimal("39.50")
        b.full_clean()  # 装叶中上更新历史批次仍允许
        b.save()

        # 可下槽上更新实测含水率仍允许
        ready = self.make_trough(Trough.STATUS_READY)
        rb = ready.batches.first()
        rb.actualMoisture = Decimal("34.80")
        rb.full_clean()
        rb.save()


class OrderingTests(TestCase):
    """乱序定义：同槽内录入顺序（id 升序）必须与开始时刻降序一致——
    后录入的批次开始时刻不得晚于先录入的批次；更新不得越过相邻录入批次。"""

    def setUp(self):
        self.now = timezone.now()
        garden = Garden.objects.create(name="测试园", altitudeBand="600m")
        self.trough = Trough.objects.create(
            garden=garden,
            troughCode="A-01",
            cultivar="福鼎大白",
            loadKg=Decimal("100.00"),
            status=Trough.STATUS_WITHERING,
        )
        self.b1 = WitherBatch.objects.create(
            trough=self.trough,
            startedAt=self.now - timezone.timedelta(hours=18),
            targetMoisture=Decimal("38.00"),
            rollGrade="一级",
        )

    def make_batch(self, started_at):
        return WitherBatch(
            trough=self.trough,
            startedAt=started_at,
            targetMoisture=Decimal("38.00"),
            rollGrade="一级",
        )

    def test_create_earlier_ok_later_rejected(self):
        # 向前补录更早批次：允许
        self.make_batch(self.now - timezone.timedelta(hours=26)).full_clean()
        # 并列时间允许（列表以 id 次序打破并列，仍可对账）
        self.make_batch(self.b1.startedAt).full_clean()
        # 晚于已有最早批次（即晚于任一批次）：拒绝
        with self.assertRaises(ValidationError) as ctx:
            self.make_batch(self.now - timezone.timedelta(hours=10)).full_clean()
        self.assertIn("startedAt", ctx.exception.message_dict)

    def test_update_cannot_cross_predecessor(self):
        b2 = WitherBatch.objects.create(
            trough=self.trough,
            startedAt=self.now - timezone.timedelta(hours=26),
            targetMoisture=Decimal("39.00"),
            rollGrade="一级",
        )
        # b2 更新到晚于上一条 b1：拒绝
        b2.startedAt = self.now - timezone.timedelta(hours=10)
        with self.assertRaises(ValidationError):
            b2.full_clean()
        # b1 更新到早于下一条 b2：拒绝
        b1 = WitherBatch.objects.get(pk=self.b1.pk)
        b1.startedAt = self.now - timezone.timedelta(hours=30)
        with self.assertRaises(ValidationError):
            b1.full_clean()
        # 仅改实测含水率不动时间：允许
        b2.startedAt = self.now - timezone.timedelta(hours=26)
        b2.actualMoisture = Decimal("38.10")
        b2.full_clean()


class BatchViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("tester", password="x")
        self.client.force_login(self.user)
        self.now = timezone.now()
        garden = Garden.objects.create(name="测试园", altitudeBand="600m")
        self.loading = Trough.objects.create(
            garden=garden,
            troughCode="L-01",
            cultivar="铁观音",
            loadKg=Decimal("90.00"),
            status=Trough.STATUS_LOADING,
        )
        self.working = Trough.objects.create(
            garden=garden,
            troughCode="W-01",
            cultivar="黄金芽",
            loadKg=Decimal("90.00"),
            status=Trough.STATUS_WITHERING,
            windowStart=self.now - timezone.timedelta(days=2),
            windowEnd=self.now + timezone.timedelta(days=1),
        )
        self.batch = WitherBatch.objects.create(
            trough=self.working,
            startedAt=self.now - timezone.timedelta(hours=5),
            targetMoisture=Decimal("38.00"),
            rollGrade="一级",
        )

    def post_batch(self, trough, started_at, **extra):
        data = {
            "trough": trough.pk,
            "startedAt": timezone.localtime(started_at).strftime("%Y-%m-%dT%H:%M"),
            "targetMoisture": "38.00",
            "actualMoisture": "",
            "rollGrade": "一级",
        }
        data.update(extra)
        return self.client.post(reverse("batch_create"), data)

    def test_loading_create_rejected_at_view(self):
        before = WitherBatch.objects.count()
        response = self.post_batch(self.loading, self.now)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "装叶中")
        self.assertEqual(WitherBatch.objects.count(), before)

    def test_outside_window_create_rejected_at_view(self):
        response = self.post_batch(
            self.working, self.now + timezone.timedelta(days=3)
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "允许窗")
        self.assertEqual(WitherBatch.objects.filter(trough=self.working).count(), 1)

    def test_valid_create_redirects_to_trough_filter(self):
        response = self.post_batch(
            self.working, self.now - timezone.timedelta(hours=8)
        )
        self.assertRedirects(
            response, f"{reverse('batch_list')}?trough={self.working.pk}"
        )

    def test_filtered_list_is_startedat_desc(self):
        other_garden = Garden.objects.create(name="另一个园", altitudeBand="800m")
        other = Trough.objects.create(
            garden=other_garden,
            troughCode="X-01",
            cultivar="龙井43",
            loadKg=Decimal("80.00"),
            status=Trough.STATUS_WITHERING,
        )
        WitherBatch.objects.create(
            trough=other,
            startedAt=self.now - timezone.timedelta(hours=1),
            targetMoisture=Decimal("38.00"),
            rollGrade="一级",
        )
        WitherBatch.objects.create(
            trough=self.working,
            startedAt=self.now - timezone.timedelta(hours=20),
            targetMoisture=Decimal("39.00"),
            rollGrade="二级",
        )
        response = self.client.get(
            reverse("batch_list"), {"trough": self.working.pk}
        )
        self.assertEqual(response.status_code, 200)
        rows = list(response.context["batches"])
        self.assertEqual({b.trough_id for b in rows}, {self.working.pk})
        times = [b.startedAt for b in rows]
        self.assertEqual(times, sorted(times, reverse=True))

    def test_update_out_of_window_rejected_at_view(self):
        bad = timezone.localtime(
            self.now + timezone.timedelta(days=3)
        ).strftime("%Y-%m-%dT%H:%M")
        response = self.client.post(
            reverse("batch_edit", args=[self.batch.pk]),
            {
                "trough": self.working.pk,
                "startedAt": bad,
                "targetMoisture": "38.00",
                "actualMoisture": "",
                "rollGrade": "一级",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "允许窗")
        self.batch.refresh_from_db()
        self.assertLess(self.batch.startedAt, self.now)

    def test_update_causing_disorder_rejected_at_view(self):
        # self.batch at -5h 是 working 槽先录入的批次；再补录一条 -20h 批次。
        earlier = WitherBatch.objects.create(
            trough=self.working,
            startedAt=self.now - timezone.timedelta(hours=20),
            targetMoisture=Decimal("39.00"),
            rollGrade="二级",
        )
        # 把更早的批次改到晚于上一条（-5h）→ 乱序，必须拒绝
        response = self.client.post(
            reverse("batch_edit", args=[earlier.pk]),
            {
                "trough": self.working.pk,
                "startedAt": timezone.localtime(
                    self.now - timezone.timedelta(hours=1)
                ).strftime("%Y-%m-%dT%H:%M"),
                "targetMoisture": "39.00",
                "actualMoisture": "",
                "rollGrade": "二级",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "乱序")
        earlier.refresh_from_db()
        self.assertLess(
            earlier.startedAt, self.now - timezone.timedelta(hours=19)
        )

    def test_update_actual_moisture_on_ready_ok(self):
        ready = Trough.objects.create(
            garden=self.working.garden,
            troughCode="R-01",
            cultivar="龙井43",
            loadKg=Decimal("80.00"),
            status=Trough.STATUS_WITHERING,
        )
        rb = WitherBatch.objects.create(
            trough=ready,
            startedAt=self.now - timezone.timedelta(hours=6),
            targetMoisture=Decimal("35.00"),
            actualMoisture=Decimal("34.90"),
            rollGrade="特级",
        )
        ready.status = Trough.STATUS_READY
        ready.save()
        response = self.client.post(
            reverse("batch_edit", args=[rb.pk]),
            {
                "trough": ready.pk,
                "startedAt": timezone.localtime(rb.startedAt).strftime(
                    "%Y-%m-%dT%H:%M"
                ),
                "targetMoisture": "35.00",
                "actualMoisture": "34.50",
                "rollGrade": "特级",
            },
        )
        self.assertEqual(response.status_code, 302)
        rb.refresh_from_db()
        self.assertEqual(rb.actualMoisture, Decimal("34.50"))
