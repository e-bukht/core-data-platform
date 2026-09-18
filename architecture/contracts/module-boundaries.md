# Module boundary contract

1. `foundation` imports standard library only.
2. `infrastructure` may depend on `foundation`, never on `host`.
3. `host` is the composition root and may depend on infrastructure/foundation.
4. Future domain contexts must not import other contexts' internal packages.
5. Framework models/ORM models are not domain entities.
