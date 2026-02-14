# UX didática (interface auto-explicativa)

Objetivo: este sistema deve funcionar como **"meu contador"** para a lavanderia. A interface precisa ser clara para um usuário que **não é contador**.

## Princípios

- Linguagem simples (evitar jargão contábil; quando inevitável, explicar).
- Explicações contextuais (próximo do campo, não só em documentação).
- Feedback imediato (mensagens de sucesso/erro dizendo o que aconteceu e o que fazer agora).
- Caminhos guiados (o usuário deve sempre saber o próximo passo).

## Checklist por tela/feature

Antes de considerar uma tela pronta:

- Existe uma frase curta dizendo **o objetivo** da tela.
- Cada campo tem:
  - rótulo claro;
  - exemplo de preenchimento quando fizer sentido;
  - dica "onde encontro essa informação" quando for comum a dúvida.
- Mensagens de validação:
  - dizem o que está errado;
  - mostram o formato esperado;
  - sugerem como corrigir.
- Números/valores calculados:
  - mostram de onde vieram (memória de cálculo);
  - deixam explícito o que é estimativa vs. valor final.

## Padrões de texto

- Preferir frases no imperativo educado e direto.
- Evitar abreviações (ou explicar quando aparecerem).

## Registros e auditoria

Sempre que o sistema importar/extrair dados externos (ex.: tabelas oficiais):

- Exibir a **fonte** e a **data de vigência**.
- Se houver fallback (html/news/pdf), deixar isso visível.
- Registrar na documentação da mudança (`docs/changes/`) o que foi alterado e como validar.
