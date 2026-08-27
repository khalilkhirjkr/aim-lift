# lifts/management/commands/import_lifts.py

import csv
from django.core.management.base import BaseCommand, CommandError
from lifts.models import Lift, Contractor # Import your models

class Command(BaseCommand):
    help = 'Imports lift and contractor data from lift_registry.csv'

    def add_arguments(self, parser):
        # Optional: Add argument for CSV file path if needed
        parser.add_argument(
            'csv_filepath', 
            type=str, 
            nargs='?', # Makes the argument optional
            default='lift_registry.csv', # Default filename
            help='The path to the lift registry CSV file.'
        )

    def handle(self, *args, **options):
        csv_filepath = options['csv_filepath']
        self.stdout.write(f"Starting import from {csv_filepath}...")

        try:
            with open(csv_filepath, mode='r', encoding='utf-8') as file:
                reader = csv.DictReader(file)

                # --- Check for required columns ---
                required_headers = ['Lift ID', 'Premise Name', 'Company', 'Latitude', 'Longitude']
                if not all(header in reader.fieldnames for header in required_headers):
                     missing = [h for h in required_headers if h not in reader.fieldnames]
                     raise CommandError(f"CSV file is missing required headers: {', '.join(missing)}")

                lifts_created_count = 0
                lifts_updated_count = 0
                contractors_created_count = 0

                for row in reader:
                    contractor_name = row.get('Company', '').strip()
                    lift_identifier = row.get('Lift ID', '').strip()
                    premise_name = row.get('Premise Name', '').strip()
                    latitude_str = row.get('Latitude', '').strip()
                    longitude_str = row.get('Longitude', '').strip()

                    if not contractor_name or not lift_identifier:
                        self.stderr.write(self.style.WARNING(f"Skipping row due to missing Contractor or Lift ID: {row}"))
                        continue

                    # --- Find or Create Contractor ---
                    contractor, contractor_created = Contractor.objects.get_or_create(
                        name=contractor_name
                    )
                    if contractor_created:
                        contractors_created_count += 1
                        self.stdout.write(f"  Created Contractor: {contractor.name}")

                    # --- Parse Coordinates ---
                    latitude = None
                    longitude = None
                    try:
                         if latitude_str:
                             latitude = float(latitude_str)
                         if longitude_str:
                             longitude = float(longitude_str)
                    except ValueError:
                         self.stderr.write(self.style.WARNING(f"  Invalid coordinates for lift {lift_identifier}, skipping: Lat='{latitude_str}', Lon='{longitude_str}'"))
                         # Decide if you want to create/update the lift without coords or skip entirely
                         # continue # Uncomment to skip if coords are invalid

                    # --- Update or Create Lift ---
                    # Use update_or_create to avoid duplicates based on lift_identifier
                    lift, lift_created = Lift.objects.update_or_create(
                        lift_identifier=lift_identifier,
                        defaults={
                            'premise_name': premise_name,
                            'contractor': contractor,
                            'latitude': latitude,
                            'longitude': longitude,
                        }
                    )

                    if lift_created:
                        lifts_created_count += 1
                        self.stdout.write(f"  Created Lift: {lift.lift_identifier} assigned to {contractor.name}")
                    else:
                        lifts_updated_count += 1
                        # Optional: Print update message if needed
                        # self.stdout.write(f"  Updated Lift: {lift.lift_identifier}")

        except FileNotFoundError:
            raise CommandError(f'Error: The file "{csv_filepath}" was not found.')
        except Exception as e:
            raise CommandError(f'An error occurred: {e}')

        self.stdout.write(self.style.SUCCESS(
            f"\nImport finished. "
            f"{contractors_created_count} contractors created. "
            f"{lifts_created_count} lifts created. "
            f"{lifts_updated_count} lifts updated."
        ))