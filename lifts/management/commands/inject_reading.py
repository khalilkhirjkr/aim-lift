"""Inject a sensor reading through the real ingest pipeline (for testing
predictive maintenance without physical hardware).

    python manage.py inject_reading --lift "WP PMA 80271" --profile fault
    python manage.py inject_reading --lift "WP PMA 80271" --profile normal --count 5
"""
from django.core.management.base import BaseCommand, CommandError

from lifts.models import Lift
from lifts.views import READING_PROFILES, build_reading_values, process_reading


class Command(BaseCommand):
    help = "Inject one or more sensor readings for a lift through the real pipeline."

    def add_arguments(self, parser):
        parser.add_argument('--lift', required=True, help="lift_identifier, e.g. 'WP PMA 80271'")
        parser.add_argument('--profile', default='normal', choices=sorted(READING_PROFILES.keys()))
        parser.add_argument('--count', type=int, default=1)

    def handle(self, *args, **opts):
        try:
            lift = Lift.objects.get(lift_identifier=opts['lift'])
        except Lift.DoesNotExist:
            raise CommandError(f"No lift with identifier {opts['lift']!r}")

        for i in range(opts['count']):
            reading = process_reading(
                lift, build_reading_values(opts['profile']),
                device_id='CLI-INJECT', source='command',
            )
            flag = '  -> incident opened' if reading.incident_id else ''
            self.stdout.write(
                f"[{i + 1}/{opts['count']}] {lift.lift_identifier}: "
                f"{reading.prediction or 'n/a'} ({reading.confidence:.1f}%){flag}"
            )
        self.stdout.write(self.style.SUCCESS("done"))
