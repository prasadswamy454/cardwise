-- Adds an optional local image for each card. Leave it NULL to keep the card's colored design.
-- Run once as a role that owns prod.cards (for example postgres, in pgAdmin's Query Tool).
ALTER TABLE prod.cards ADD COLUMN image_url character varying;

-- To give a card an image, save the file in the project's images/ folder and run, for example:
-- UPDATE prod.cards SET image_url = 'images/capitalone-savor.png' WHERE id = 'capitalone-savor';
