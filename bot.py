Нашёл несколько проблем — от критических до незначительных.

---

**🔴 Критическое — гонка данных в `sub_balance`**

cur.execute(f"SELECT {field} FROM users WHERE user_id=?", (uid,))
r = cur.fetchone()
if not r or r[0] < amount:
    return False
cur.execute(f"UPDATE users SET {field} = {field} - ? WHERE user_id=?", (amount, uid))


Между SELECT и UPDATE другой поток успеет списать тот же баланс. Это двойное списание реальных денег. Нужно одним атомарным запросом:

cur.execute(
    f"UPDATE users SET {field} = {field} - ? WHERE user_id=? AND {field} >= ?",
    (amount, uid, amount)
)
return cur.rowcount > 0


---

**🔴 Критическое — `bot = None` при вызове `safe_send` / `safe_photo`**

Если `safe_send` вызовется до инициализации бота (например, из потока при старте), будет `AttributeError: 'NoneType' object has no attribute 'send_message'`. Нужна проверка:

if bot is None:
    return None


---

**🟡 Среднее — `rub_to_stars` делит на ноль**

`STARS_RUB_PER_STAR` берётся из ENV без проверки `> 0`. Если кто-то выставит `0`, будет `ZeroDivisionError`. `_env_float` не имеет минимального порога (в отличие от `_env_int`).

---

**🟡 Среднее — `safe_photo` прерывает retry на первой же не-сетевой ошибке**

Внутри цикла `for i in range(3)` при ошибке, которая не сетевая, функция сразу делает `return None`, не делая 3 попытки. Это ожидаемое поведение? Если да — уберите цикл и оставьте одну попытку, иначе логика вводит в заблуждение.

---

**🟢 Мелкое — `add_user` не хранит курсор**

c.cursor().execute(...)


Курсор создаётся и сразу выбрасывается. Работает из-за `isolation_level=None` (autocommit), но лучше явно:

cur = c.cursor()
cur.execute(...)


---

**Итог:** самое срочное — переписать `sub_balance` на атомарный UPDATE. Гонка там реальная при любом параллельном использовании бота.