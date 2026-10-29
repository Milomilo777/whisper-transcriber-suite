// A minimal stand-in for Cloudflare D1 on top of node:sqlite, so the tests run the Worker's real SQL
// against the real schema.sql. Only the calls the Worker uses: prepare().bind().run()/all()/first(),
// and batch().
import { DatabaseSync } from 'node:sqlite';
import { readFileSync } from 'node:fs';

export function fakeD1() {
  const db = new DatabaseSync(':memory:');
  db.exec(readFileSync(new URL('../schema.sql', import.meta.url), 'utf8'));
  const counters = { statements: 0 };

  function statement(sql, args = []) {
    const run = () => {
      counters.statements++;
      const info = db.prepare(sql).run(...args);
      return { success: true, meta: { last_row_id: Number(info.lastInsertRowid), changes: Number(info.changes) } };
    };
    return {
      bind: (...values) => statement(sql, values),
      run: async () => run(),
      all: async () => {
        counters.statements++;
        return { success: true, results: db.prepare(sql).all(...args).map((r) => ({ ...r })) };
      },
      first: async () => {
        counters.statements++;
        const row = db.prepare(sql).get(...args);
        return row ? { ...row } : null;
      },
      _run: run,
    };
  }

  return {
    prepare: (sql) => statement(sql),
    batch: async (statements) => {
      // D1 runs a batch as one transaction: all statements or none.
      db.exec('BEGIN');
      try {
        const out = statements.map((s) => s._run());
        db.exec('COMMIT');
        return out;
      } catch (e) {
        db.exec('ROLLBACK');
        throw e;
      }
    },
    raw: db,
    counters,
  };
}
