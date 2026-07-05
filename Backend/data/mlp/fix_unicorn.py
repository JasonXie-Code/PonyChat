# -*- coding: utf-8 -*-
import sqlite3
from mlp_paths import DB_PATH

conn = sqlite3.connect(str(DB_PATH))
conn.execute("UPDATE mlp_knowledge SET importance='major' WHERE filename='独角兽.txt'")
conn.commit()
print("done, rows affected:", conn.total_changes)
conn.close()
