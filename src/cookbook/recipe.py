"""Validated presentation data for one selected everyday recipe."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


ShortText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
RecipeText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]


class RecipeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecipeCitation(RecipeModel):
    publication_id: ShortText
    book_id: ShortText
    source_id: ShortText
    section_id: ShortText


class RecipeSource(RecipeModel):
    kind: Literal["original", "book", "adapted"]
    label: ShortText = Field(description="Book title and author, or 'Original recipe'.")
    note: RecipeText | None = Field(
        default=None,
        description="Source page/section, or concise explanation of adaptations. No invented attribution.",
    )
    citations: list[RecipeCitation] = Field(
        default_factory=list,
        max_length=8,
        description="Exact identifiers returned by read_section. Required for book/adapted recipes.",
    )

    @model_validator(mode="after")
    def require_book_citation(self):
        if self.kind != "original" and not self.citations:
            raise ValueError("Book recipes require source citations")
        return self


class RecipeStep(RecipeModel):
    title: ShortText = Field(
        description="Short action, e.g. 'Brown the mushrooms'. No prerequisite subtitle."
    )
    ingredients: list[ShortText] = Field(
        max_length=16,
        description="Quantities needed for THIS action, e.g. '300 g mushrooms', '1 tbsp olive oil'. Split divided quantities explicitly; do not repeat the full amount at every use.",
    )
    method: RecipeText = Field(
        description="Complete instructions including prep at its point of use, heat, timing and doneness. Mention useful safe overlap in this prose; preserve dependencies. No separate prep phase or readiness subtitle."
    )


class RecipeCard(RecipeModel):
    title: ShortText
    metadata: list[ShortText] = Field(
        default_factory=list,
        max_length=4,
        description="Short facts, e.g. ['30 minutes', 'Serves 2', 'Vegetarian']. Omit unknown facts.",
    )
    description: ShortText | None = Field(
        default=None,
        description="Optional one-sentence dish description, visible when compact.",
    )
    steps: list[RecipeStep] = Field(
        min_length=1,
        max_length=12,
        description="Everyday recipe actions in cooking order, each paired with its ingredients.",
    )
    source: RecipeSource
