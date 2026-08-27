# lifts/management/commands/clear_predictions.py

from django.core.management.base import BaseCommand
from lifts.models import Incident

class Command(BaseCommand):
    help = 'Deletes all predictive maintenance incident logs (those starting with "Predicted:")'

    def handle(self, *args, **options):
        # Find incidents whose type starts with "Predicted:"
        predictive_incidents = Incident.objects.filter(incident_type__startswith='Predicted:')

        count = predictive_incidents.count()

        if count > 0:
            # Delete them
            predictive_incidents.delete()
            self.stdout.write(self.style.SUCCESS(f'Successfully deleted {count} predictive incident logs.'))
        else:
            self.stdout.write(self.style.NOTICE('No predictive incident logs found to delete.'))