# Generated manually for adding managers field to WishList
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gift', '0006_wikiuser_scraped_page_selected_alter_item_name_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='wishlist',
            name='managers',
            field=models.ManyToManyField(
                blank=True,
                help_text='Additional users who can manage this list',
                related_name='managed_wishlists',
                to='gift.wikiuser'
            ),
        ),
        migrations.AlterField(
            model_name='wishlist',
            name='title',
            field=models.CharField(max_length=255),
        ),
    ]

