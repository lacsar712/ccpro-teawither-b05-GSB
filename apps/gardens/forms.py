from django import forms
from django.utils import timezone

from .models import Garden, Trough, WitherBatch

_DATETIME_INPUT_FORMATS = [
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
]


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
        self.fields["windowStart"].input_formats = _DATETIME_INPUT_FORMATS
        self.fields["windowEnd"].input_formats = _DATETIME_INPUT_FORMATS
        self.fields["windowStart"].required = False
        self.fields["windowEnd"].required = False
        if self.instance and self.instance.pk:
            if self.instance.windowStart:
                self.initial["windowStart"] = timezone.localtime(
                    self.instance.windowStart
                ).strftime("%Y-%m-%dT%H:%M")
            if self.instance.windowEnd:
                self.initial["windowEnd"] = timezone.localtime(
                    self.instance.windowEnd
                ).strftime("%Y-%m-%dT%H:%M")


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
        self.fields["startedAt"].input_formats = _DATETIME_INPUT_FORMATS
        if self.instance and self.instance.pk and self.instance.startedAt:
            local = timezone.localtime(self.instance.startedAt)
            self.initial["startedAt"] = local.strftime("%Y-%m-%dT%H:%M")
