from django.db import models


class FuelStation(models.Model):
    GEOCODE_STATUS = [
        ("pending", "Pending"),
        ("exact", "Exact"),
        ("non_exact", "Non Exact"),
        ("fallback", "Fallback"),
        ("failed", "Failed"),
    ]

    opis_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=10)
    rack_id = models.IntegerField()

    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )

    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )

    geocode_status = models.CharField(
        max_length=20,
        choices=GEOCODE_STATUS,
        default="pending",
    )

    def __str__(self):
        return f"{self.name} - {self.city}, {self.state}"


class FuelPrice(models.Model):
    station = models.ForeignKey(
        FuelStation,
        on_delete=models.CASCADE,
        related_name="prices",
    )

    price = models.DecimalField(
        max_digits=8,
        decimal_places=6,
    )

    def __str__(self):
        return f"{self.station.name} - ${self.price}"
