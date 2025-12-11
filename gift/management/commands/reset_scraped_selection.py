from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = 'Reset scraped page selection for a user (for testing)'

    def add_arguments(self, parser):
        parser.add_argument(
            'username',
            type=str,
            help='Username of the user to reset'
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Reset selection for all users'
        )

    def handle(self, *args, **options):
        if options['all']:
            users = User.objects.filter(scraped_page_selected=True)
            count = users.count()
            for user in users:
                user.scraped_page_selected = False
                user.selected_scraped_page = None
                user.save()
                # Also mark the scraped page as not imported if it exists
                if user.selected_scraped_page:
                    user.selected_scraped_page.is_imported = False
                    user.selected_scraped_page.imported_by = None
                    user.selected_scraped_page.save()
            
            self.stdout.write(
                self.style.SUCCESS(f'Reset selection for {count} users')
            )
        else:
            username = options['username']
            try:
                user = User.objects.get(username=username)
                old_page = user.selected_scraped_page
                
                user.scraped_page_selected = False
                user.selected_scraped_page = None
                user.save()
                
                # Mark the scraped page as not imported if it exists
                if old_page:
                    old_page.is_imported = False
                    old_page.imported_by = None
                    old_page.save()
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'Reset selection for {username}. '
                            f'Scraped page "{old_page.title}" is now available again.'
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.SUCCESS(f'Reset selection for {username}')
                    )
            except User.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'User "{username}" not found')
                )



