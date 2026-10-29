from alembic import context
from app.db.session import Base, engine
import app.models  # register metadata

if context.is_offline_mode():
    context.configure(url=str(engine.url), target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with engine.connect() as connection:
        if engine.dialect.name == 'sqlite':
            # SQLite batch table rebuilds must temporarily suspend FK enforcement on this migration connection.
            connection.exec_driver_sql('PRAGMA foreign_keys=OFF')
            connection.commit()
        context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=engine.dialect.name == 'sqlite')
        with context.begin_transaction():
            context.run_migrations()
        if engine.dialect.name == 'sqlite':
            violations = connection.exec_driver_sql('PRAGMA foreign_key_check').fetchall()
            connection.commit()
            connection.exec_driver_sql('PRAGMA foreign_keys=ON')
            connection.commit()
            if violations:
                raise RuntimeError('Foreign-key validation failed after SQLite migration')
