class TarantoolRouter:
    """Route room reads and writes to the Tarantool Django backend."""

    route_model = ("core", "room")

    def db_for_read(self, model, **hints):
        if (model._meta.app_label, model._meta.model_name) == self.route_model:
            return "tarantool"
        return None

    def db_for_write(self, model, **hints):
        if (model._meta.app_label, model._meta.model_name) == self.route_model:
            return "tarantool"
        return None

    def allow_relation(self, obj1, obj2, **hints):
        if obj1._state.db in {"default", "tarantool"} and obj2._state.db in {"default", "tarantool"}:
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if (app_label, model_name) == self.route_model:
            return db == "tarantool"
        if db == "tarantool":
            return False
        return None
