- Follow the practices of principal software engineers.
- When useful, follow the idea that "code should operate on domain model, not on data directly" & law of demeter.
- Avoid python base types -> prefer enums, classes, alias, etc.
- Never "hack" in a solution. Long term maintainability & quality is the goal, not speed.
- No "magic numbers" or other magic variables.
- Follow best practices for the arrangement of your code. SIMPLER and READABLE is almost always better.
- Comments should not describe *what* the code does but rather the *whys* behind the code (things like decisions, tradeoffs, learned best practices, experiences, incompletes, implicit assumptions).
- Docstrings are documentation for people who use or maintain your code.

Where this project is going:

zidgag next
	What to do next

zigdag check
	Design
	Architecture
	Security
	Typecheck
	Lint

Zigdag test
	Tests
	Contract Tests
	Mutation Tests (find bad tests + contracts)
	Performance Tests (todo)

Zigdag context <file>

Zigdag review <base>

Works for Python, Terraform, Web/Typescript, …

- I don't want you to flood me with information EVER. I don't EVER want you to talk like a tech bro
  or however you think a coder should talk. Talk naturally. Talk how you want to talk. Talk like you
  breathe and like you've taken the thinking burden so your reader doesn't have to. Talk like you're not
  trying to make me happy by flooding me with info and hoping I'll say yes. Make it really easy for me to
  tell whether what you're saying is right or wrong, or spot concerns and flaws, make it easy for me to
  get the idea and build it from first principles, make it easy :)
