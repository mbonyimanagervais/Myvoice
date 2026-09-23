================================================================
MYVOICE HOMEPAGE IMAGES FOLDER
================================================================

Drop your photos here and they will be displayed in the
homepage hero rotation automatically.

================================================================
FOLDER STRUCTURE
================================================================

static/images/homepage/
    |
    +-- slides/           <-- ACTIVE IMAGES ROTATED IN HERO
    |     image-01.jpg
    |     image-02.jpg
    |     image-03.jpg
    |     image-04.jpg
    |     image-05.jpg
    |     image-06.jpg
    |
    +-- upload/           <-- DROP NEW IMAGES HERE FIRST
    |     (then run: python _organize_homepage_images.py)
    |
    +-- backup/           <-- BACKUP OF OLD IMAGES

================================================================
HOW TO ADD NEW IMAGES
================================================================

1. Save your photos (jpg / jpeg / png) into:
       static/images/homepage/upload/

2. Run this command in the project folder:
       python _organize_homepage_images.py

3. The script will:
   - Rename files to image-01.jpg, image-02.jpg, ... image-99.jpg
   - Move them to the slides/ folder
   - Backup the previous slides/ images to backup/

4. Restart the Flask app and the new images will rotate.

================================================================
SUPPORTED FILE TYPES
================================================================

- .jpg
- .jpeg
- .png

================================================================
RECOMMENDED IMAGE SIZE
================================================================

For best results, use:
- Width:  1920 pixels
- Height: 1080 pixels (or 1200 for a bit more vertical space)
- File size: 200KB - 500KB (compressed)
- Format: JPG (best for photos)

================================================================
CURRENT IMAGES
================================================================

The slides/ folder currently contains:
  image-01.jpg   (Kigali city aerial)
  image-02.jpg   (Kigali fountain)
  image-03.jpg   (Voting rights ballot)
  image-04.jpg   (Hand inserting ballot)
  image-05.jpg   (Hand over ballot box)
  image-06.jpg   (VOTE digital button)

To use the new images you provided (FR RAMON KABUGA TSS):
  - Father Ramon Kabuga photo
  - FR RAMON KABUGA TSS students
  - School logo/badge
  - Students in workshop
  - Rwanda students group
  - Student at machinery
  - Kigali city aerial (better version)
  etc.

Just save them to /upload/ and run the organizer script.

================================================================
