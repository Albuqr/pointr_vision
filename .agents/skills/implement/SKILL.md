---
name: implement
description: "Implement a piece of work based on a spec or set of tickets."
disable-model-invocation: true
---

Implement the work described by the user in the spec or tickets.

If the user passes a ticket reference, fetch it from the issue tracker and state its title before starting. If the reference is ambiguous, ask.

Call the Skill tool with "tdd" where possible, at pre-agreed seams.

Run typechecking regularly, single test files regularly, and the full test suite once at the end.

Once done, call the Skill tool with "code-review" to review the work.

Commit your work to the current branch.

Branches: start each ticket on a fresh branch cut from the latest `origin/main`, never on a branch whose PR has already merged. Once the PR is accepted, close the branch: delete it locally and on the remote, then leave the checkout on an up-to-date `main`. Open the PR with `Closes #<n>`.
