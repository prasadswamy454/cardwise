-- Points the default wallet cards at their local images in the images/ folder.
-- Those files are not in git, so a fresh checkout shows the colored designs until they are added.
-- Run once as a role that owns prod.cards (for example postgres, in pgAdmin's Query Tool), connected to cardwise.
UPDATE prod.cards SET image_url = 'images/capitalone-savor.png' WHERE id = 'capitalone-savor';
UPDATE prod.cards SET image_url = 'images/chase-freedom-unlimited.png' WHERE id = 'chase-freedom-unlimited';
UPDATE prod.cards SET image_url = 'images/wells-active-cash.png' WHERE id = 'wells-active-cash';
UPDATE prod.cards SET image_url = 'images/chase-sapphire-preferred.jpeg' WHERE id = 'chase-sapphire-preferred';
