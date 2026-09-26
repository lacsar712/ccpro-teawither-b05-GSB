from django import forms
from django.utils import timezone

from .models import Garden, Trough, WitherBatch

DATETIME_INPUT_FORMATS = [
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
]


def _localize_initial(form, field_names):
    """编辑时把 aware datetime 初始值格式化为 datetime-local 本地串。"""
    if not (form.instance and form.instance.pk):
        return
    for name in field_names:
        value = getattr(form.instance, name, None)
        if value:
            form.initial[name] = timezone.localtime(value).strftime("%Y-%m-%dT%H:%M")


class GardenForm(forms.ModelForm):
    class Meta:
        model = Garden
        fields = ["name", "altitudeBand", "notes"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input"}),
            "altitudeBand": forms.TextInput(attrs={"class": "input"}),
            "notes": forms.Textarea(attrs={"class": "input", "rows": 3}),
        }


class TroughForm(forms.ModelForm):
    class Meta:
        model = Trough
        fields = [
            "garden",
            "troughCode",
            "cultivar",
            "loadKg",
            "status",
            "windowStart",
            "windowEnd",
        ]
        widgets = {
            "garden": forms.Select(attrs={"class": "input"}),
            "troughCode": forms.TextInput(attrs={"class": "input"}),
            "cultivar": forms.TextInput(attrs={"class": "input"}),
            "loadKg": forms.NumberInput(attrs={"class": "input", "step": "0.01"}),
            "status": forms.Select(attrs={"class": "input"}),
            "windowStart": forms.DateTimeInput(
                attrs={"class": "input", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "windowEnd": forms.DateTimeInput(
                attrs={"class": "input", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("windowStart", "windowEnd"):
            self.fields[name].input_formats = DATETIME_INPUT_FORMATS
        _localize_initial(self, ("windowStart", "windowEnd"))


class WitherBatchForm(forms.ModelForm):
    class Meta:
        model = WitherBatch
        fields = [
            "trough",
            "startedAt",
            "targetMoisture",
            "actualMoisture",
            "rollGrade",
        ]
        widgets = {
            "trough": forms.Select(attrs={"class": "input"}),
            "startedAt": forms.DateTimeInput(
                attrs={"class": "input", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "targetMoisture": forms.NumberInput(
                attrs={"class": "input", "step": "0.01"}
            ),
            "actualMoisture": forms.NumberInput(
                attrs={"class": "input", "step": "0.01"}
            ),
            "rollGrade": forms.TextInput(attrs={"class": "input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["startedAt"].input_formats = DATETIME_INPUT_FORMATS
        _localize_initial(self, ("startedAt",))
