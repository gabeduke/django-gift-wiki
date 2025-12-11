# Generated manually to add profile_picture fields to WikiUser

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gift', '0004_add_price_range_to_item'),
    ]

    operations = [
        migrations.AddField(
            model_name='wikiuser',
            name='profile_picture',
            field=models.ImageField(blank=True, help_text='Profile picture (will be automatically resized)', null=True, upload_to='profile_pictures/'),
        ),
        migrations.AddField(
            model_name='wikiuser',
            name='profile_picture_thumbnail',
            field=models.ImageField(blank=True, help_text='Thumbnail version (150x150)', null=True, upload_to='profile_pictures/thumbnails/'),
        ),
        migrations.AddField(
            model_name='wikiuser',
            name='profile_picture_web',
            field=models.ImageField(blank=True, help_text='Web version (400x400)', null=True, upload_to='profile_pictures/web/'),
        ),
    ]



