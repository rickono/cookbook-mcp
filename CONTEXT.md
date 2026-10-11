# Cookbook Library

A personal cookbook library for finding recipes, reading their content, and
tracing that content to the source books.

## Language

**Book edition**:
A particular source representation of a book, identified by its original bytes.
Different editions and formats can describe the same work while remaining distinct sources.

**Chapter**:
An authored division of a book containing recipes, prose, or other material.
A chapter can continue across source files.

**Recipe**:
An authored preparation, including its ingredients, instructions, associated prose,
and any local parts or variations. It can itself be used in another recipe.

**Recipe part**:
An authored group within a recipe, such as a preparation, ingredient group,
method group, equipment list, variation, or final assembly.

**Recipe ingredient**:
One authored ingredient requirement within a particular recipe or recipe part.
Repeated requirements for the same ingredient remain separate occurrences.

**Recipe formulation**:
A named ingredient set and yield for a recipe, such as its small or large batch.
Formulations may share instructions.

**Recipe use**:
A recipe's use of another preparation, with its requiredness, amount, selected
formulation or variation, and whole or partial scope recorded separately.

**Ingredient allocation**:
A portion of one recipe ingredient assigned to a particular stage of preparation.

**Passage**:
A source-backed piece of prose, such as an essay, headnote, quotation, technique,
or note. A passage can be addressed independently of a recipe.

**Reference entry**:
An authored entry about a subject, such as an ingredient, wine region, or cuisine,
including its prose and reference information.

**Pairing assertion**:
An authored recommendation that two or more flavors work together.
A group recommendation retains all its participants together.

**Supporting work**:
The preparations and techniques needed for a selected recipe, formulation, or
variation, including any stated partial preparation and unresolved requirements.

**Recipe request**:
A description of the recipes a person is looking for, including concrete
requirements, subjective preferences, or both.

**Recipe match**:
A recipe judged suitable for a recipe request, with source-backed evidence of
its fit and any remaining uncertainty identified.

**Usable PDF cookbook**:
A PDF cookbook whose recipes can be found, whose complete ingredients and
instructions can be read, and whose original pages can be cited. Corrections are
reviewed and unresolved content is clearly identified.

**Correction**:
A change to a transcription supported by the original page's visible content.
A correction does not change the original book.

**Unresolved content**:
Content whose correct transcription or completeness has not yet been established.
It remains explicitly identified rather than being filled in by inference.

**Agent review**:
A review pass in which an agent examines the source and candidate transcription,
attempts source-supported recovery, and identifies remaining uncertainty. Whether
its result qualifies as approved content is a separate decision.

**Human edge case**:
Uncertainty that remains after agent review and requires the owner's judgment,
source inspection, or a better scan. The escalation criteria are not yet settled.
