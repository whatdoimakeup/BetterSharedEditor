-- Tarantool initialization script

-- Configure Tarantool to listen on all interfaces
box.cfg({
    listen = '0.0.0.0:3301',
    wal_mode = 'none',
})

if not box.schema.user.exists('admin') then
    box.schema.user.create('admin', {password = 'password'})
else
    -- Если пользователь уже есть, явно обновляем пароль
    box.schema.user.passwd('admin', 'password')
end

-- Grant admin privileges idempotently
box.schema.user.grant('admin', 'super', nil, nil, {if_not_exists = true})

-- Wait until box is initialized
box.once('init_v1', function()
    -- Create spaces for the application

    -- Rooms space: stores collaborative editing rooms
    -- Fields: id (unsigned), name (string), created_at (string),
    --         yjs_state (binary), content (string), updated_at (string)
    local rooms = box.schema.space.create('rooms', {
        if_not_exists = true,
        format = {
            {name = 'id',           type = 'unsigned'},
            {name = 'name',         type = 'string'},
            {name = 'created_at',   type = 'string'},
            {name = 'yjs_state',    type = 'varbinary',  is_nullable = true},
            {name = 'content',      type = 'string',     is_nullable = true},
            {name = 'updated_at',   type = 'string'},
        }
    })

    -- Primary index on id
    rooms:create_index('primary', {
        type = 'TREE',
        parts = {{field = 'id', type = 'unsigned'}},
        if_not_exists = true,
    })

    -- Grant access to the admin user
    box.schema.user.grant('admin', 'read,write,execute', 'space', 'rooms', {if_not_exists = true})
end)

print("Tarantool initialized successfully")
