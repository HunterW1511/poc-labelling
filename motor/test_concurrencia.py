"""L.10: prioridades del motor sin SAM 3 (cola semantica vs precodificacion interactiva). Uso: python /app/test_concurrencia.py"""
import cola
import interactivo

modo = interactivo.INTERACTIVO
interactivo.INTERACTIVO = "completo"     # P.3.5: la precodificacion local solo existe en modo completo
avisos = []
cola.al_vaciar.append(lambda: avisos.append(1))
assert not cola.ocupada(), "al arrancar no hay trabajo"
interactivo._est["pred"], interactivo._est["calentando"] = object(), False
interactivo._ev.clear()
assert interactivo._puede_precodificar(), "sin cola, la precodificacion puede correr"
cola._cola.put(({"id": 1}, {}, "v"))
cola._pendientes.add(1)
assert cola.ocupada() and not interactivo._puede_precodificar(), "con cola semantica, la precodificacion cede la CPU"
cola._cola.get()
cola._terminar(1)
assert not cola.ocupada() and avisos == [1], f"al vaciarse avisa una vez: {avisos}"
assert interactivo._ev.is_set() and interactivo._puede_precodificar(), "al vaciarse se reanuda la precodificacion"
interactivo.INTERACTIVO = "liviano"
assert not interactivo._puede_precodificar(), "liviano: nunca precodifica en el hub"
interactivo._est["pred"], interactivo.INTERACTIVO = None, modo
print("TEST CONCURRENCIA OK: la precodificacion cede ante la cola y se reanuda al vaciarse")