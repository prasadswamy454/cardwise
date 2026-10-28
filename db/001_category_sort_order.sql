-- Gives spending categories an explicit display order. The UI preselects the first category.
-- Run once as a role that owns prod.categories (for example postgres, in pgAdmin's Query Tool).
BEGIN;

ALTER TABLE prod.categories ADD COLUMN sort_order integer;

UPDATE prod.categories AS c
SET sort_order = v.sort_order
FROM (VALUES ('groceries', 1), ('dining', 2), ('gas', 3), ('ev', 4),
             ('travel', 5), ('shopping', 6), ('other', 7)) AS v (id, sort_order)
WHERE c.id = v.id;

ALTER TABLE prod.categories ALTER COLUMN sort_order SET NOT NULL;
ALTER TABLE prod.categories ADD CONSTRAINT categories_sort_order_key UNIQUE (sort_order);

COMMIT;
