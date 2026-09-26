from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import WitherBatchForm
from .models import Garden, Trough, WitherBatch
from .seed import ensure_seed_data


def batch_data(trough, started, **kw):
    data = {
        "trough": trough.pk,
        # 表单按本地墙钟解析 datetime-local，先转本地再格式化
        "startedAt": timezone.localtime(started).strftime("%Y-%m-%dT%H:%M"),
        "targetMoisture": "38.00",
        "actualMoisture": "",
        "rollGrade": "一级",
    }
    data.update(kw)
    return data


class BatchRuleTestCase(TestCase):
    def setUp(self):
        self.garden = Garden.objects.create(name="测试园", altitudeBand="800m")
        # datetime-local 表单精度为分钟，对齐到分钟模拟真实录入
        self.now = timezone.now().replace(second=0, microsecond=0)
        self.ws = self.now - timedelta(days=3)
        self.we = self.now + timedelta(days=3)

    def make_trough(self, code, status=Trough.STATUS_WITHERING):
        return Trough.objects.create(
            garden=self.garden,
            troughCode=code,
            cultivar="福鼎大白",
            loadKg=Decimal("100.00"),
            status=status,
            windowStart=self.ws,
            windowEnd=self.we,
        )

    def make_ready_trough(self, code):
        trough = self.make_trough(code)
        self.make_batch(
            trough,
            self.now - timedelta(hours=2),
            actualMoisture=Decimal("35.00"),
        )
        trough.status = Trough.STATUS_READY
        trough.save()
        return trough

    def make_batch(self, trough, started, **kw):
        defaults = {
            "targetMoisture": Decimal("38.00"),
            "actualMoisture": None,
            "rollGrade": "一级",
        }
        defaults.update(kw)
        return WitherBatch.objects.create(
            trough=trough, startedAt=started, **defaults
        )


class StatusInterlockTest(BatchRuleTestCase):
    def test_create_blocked_on_loading_trough(self):
        trough = self.make_trough("L-01", Trough.STATUS_LOADING)
        form = WitherBatchForm(data=batch_data(trough, self.now))
        self.assertFalse(form.is_valid())
        self.assertIn("trough", form.errors)
        # 模型层同样拦截
        with self.assertRaises(ValidationError):
            self.make_batch(trough, self.now)

    def test_create_allowed_on_withering_trough(self):
        trough = self.make_trough("W-01")
        form = WitherBatchForm(data=batch_data(trough, self.now))
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(WitherBatch.objects.count(), 1)

    def test_create_allowed_on_ready_trough(self):
        trough = self.make_ready_trough("R-01")
        form = WitherBatchForm(data=batch_data(trough, self.now))
        self.assertTrue(form.is_valid(), form.errors)

    def test_update_allowed_on_loading_trough(self):
        trough = self.make_trough("L-02")
        batch = self.make_batch(trough, self.now - timedelta(hours=1))
        trough.status = Trough.STATUS_LOADING
        trough.save()
        form = WitherBatchForm(
            instance=batch,
            data=batch_data(
                trough, self.now - timedelta(hours=1), actualMoisture="37.50"
            ),
        )
        self.assertTrue(form.is_valid(), form.errors)


class WindowTest(BatchRuleTestCase):
    def test_create_outside_window_rejected(self):
        trough = self.make_trough("W-02")
        before = WitherBatchForm(
            data=batch_data(trough, self.ws - timedelta(hours=1))
        )
        self.assertFalse(before.is_valid())
        self.assertIn("startedAt", before.errors)
        after = WitherBatchForm(
            data=batch_data(trough, self.we + timedelta(hours=1))
        )
        self.assertFalse(after.is_valid())
        self.assertIn("startedAt", after.errors)

    def test_create_on_window_boundary_allowed(self):
        trough = self.make_trough("W-03")
        form = WitherBatchForm(data=batch_data(trough, self.ws))
        self.assertTrue(form.is_valid(), form.errors)

    def test_update_outside_window_rejected(self):
        trough = self.make_trough("W-04")
        batch = self.make_batch(trough, self.now)
        form = WitherBatchForm(
            instance=batch,
            data=batch_data(trough, self.we + timedelta(hours=1)),
        )
        self.assertFalse(form.is_valid())
        self.assertIn("startedAt", form.errors)

    def test_trough_window_must_be_ordered(self):
        with self.assertRaises(ValidationError):
            Trough.objects.create(
                garden=self.garden,
                troughCode="BAD-01",
                cultivar="福鼎大白",
                loadKg=Decimal("100.00"),
                status=Trough.STATUS_WITHERING,
                windowStart=self.we,
                windowEnd=self.ws,
            )


class OutOfOrderTest(BatchRuleTestCase):
    def test_create_earlier_than_existing_later_batch_rejected(self):
        trough = self.make_trough("O-01")
        self.make_batch(trough, self.now - timedelta(hours=5))
        # 槽内已存在开始时刻更晚的批次，新批次早于其开始 → 乱序，拒绝
        form = WitherBatchForm(
            data=batch_data(trough, self.now - timedelta(hours=6))
        )
        self.assertFalse(form.is_valid())
        self.assertIn("startedAt", form.errors)
        # 不早于现有最晚开始时刻 → 允许
        ok = WitherBatchForm(
            data=batch_data(trough, self.now - timedelta(hours=4))
        )
        self.assertTrue(ok.is_valid(), ok.errors)

    def test_update_must_not_move_after_later_created_batch(self):
        trough = self.make_trough("O-02")
        self.make_batch(trough, self.now - timedelta(hours=10))
        b2 = self.make_batch(trough, self.now - timedelta(hours=8))
        self.make_batch(trough, self.now - timedelta(hours=6))
        form = WitherBatchForm(
            instance=b2,
            data=batch_data(trough, self.now - timedelta(hours=5)),
        )
        self.assertFalse(form.is_valid())
        self.assertIn("startedAt", form.errors)

    def test_update_must_not_move_before_earlier_created_batch(self):
        trough = self.make_trough("O-03")
        self.make_batch(trough, self.now - timedelta(hours=10))
        b2 = self.make_batch(trough, self.now - timedelta(hours=8))
        form = WitherBatchForm(
            instance=b2,
            data=batch_data(trough, self.now - timedelta(hours=11)),
        )
        self.assertFalse(form.is_valid())
        self.assertIn("startedAt", form.errors)

    def test_update_within_neighbours_allowed(self):
        trough = self.make_trough("O-04")
        self.make_batch(trough, self.now - timedelta(hours=10))
        b2 = self.make_batch(trough, self.now - timedelta(hours=8))
        b3 = self.make_batch(trough, self.now - timedelta(hours=6))
        form = WitherBatchForm(
            instance=b2,
            data=batch_data(trough, self.now - timedelta(hours=9)),
        )
        self.assertTrue(form.is_valid(), form.errors)
        # 最晚创建的批次继续后移允许（没有更晚创建的批次）
        form = WitherBatchForm(
            instance=b3,
            data=batch_data(trough, self.now - timedelta(hours=1)),
        )
        self.assertTrue(form.is_valid(), form.errors)


class ReadyTroughUpdateTest(BatchRuleTestCase):
    def test_update_actual_moisture_on_ready_trough_allowed(self):
        trough = self.make_ready_trough("R-02")
        batch = trough.batches.get()
        form = WitherBatchForm(
            instance=batch,
            data=batch_data(
                trough, self.now - timedelta(hours=2), actualMoisture="36.50"
            ),
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        batch.refresh_from_db()
        self.assertEqual(batch.actualMoisture, Decimal("36.50"))

    def test_update_started_at_on_ready_trough_still_constrained(self):
        trough = self.make_ready_trough("R-03")
        batch = trough.batches.get()
        form = WitherBatchForm(
            instance=batch,
            data=batch_data(trough, self.we + timedelta(hours=1)),
        )
        self.assertFalse(form.is_valid())
        self.assertIn("startedAt", form.errors)


class BatchListFilterTest(BatchRuleTestCase):
    def test_filter_by_trough_and_ordering(self):
        user = get_user_model().objects.create_user("viewer", password="pw")
        self.client.force_login(user)
        t1 = self.make_trough("F-01")
        t2 = self.make_trough("F-02")
        b1 = self.make_batch(t1, self.now - timedelta(hours=3))
        b2 = self.make_batch(t1, self.now - timedelta(hours=1))
        b3 = self.make_batch(t2, self.now - timedelta(hours=2))

        resp = self.client.get(reverse("batch_list"), {"trough": t1.pk})
        self.assertEqual(resp.status_code, 200)
        batches = list(resp.context["batches"])
        # 按槽过滤后只剩该槽批次，且顺序与开始时刻倒序一致
        self.assertEqual([b.pk for b in batches], [b2.pk, b1.pk])

        resp = self.client.get(reverse("batch_list"))
        batches = list(resp.context["batches"])
        self.assertEqual([b.pk for b in batches], [b2.pk, b3.pk, b1.pk])


class SeedTest(TestCase):
    def test_seed_has_trough_with_multiple_batches_in_order(self):
        ensure_seed_data()
        trough = Trough.objects.get(troughCode="A-01")
        self.assertGreaterEqual(trough.batches.count(), 2)
        starts = list(trough.batches.order_by("id").values_list("startedAt", flat=True))
        self.assertEqual(starts, sorted(starts))
        # 所有批次开始时刻均落在所属槽允许窗内
        for batch in trough.batches.all():
            self.assertLessEqual(trough.windowStart, batch.startedAt)
            self.assertLessEqual(batch.startedAt, trough.windowEnd)
