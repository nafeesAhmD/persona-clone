"""The fixed marketplace categories (slug -> name, description)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    slug: str
    name: str
    description: str


CATEGORIES: tuple[Category, ...] = (
    Category("education", "Education & Tutoring", "Teachers, tutors and study help."),
    Category("technology", "Technology & Programming", "Software, data, IT and engineering."),
    Category("business", "Business & Career", "Entrepreneurs, managers and career advice."),
    Category("health", "Health & Wellness", "Fitness, nutrition and wellbeing (not medical advice)."),
    Category("creative", "Creative & Arts", "Writers, designers, artists and musicians."),
    Category("lifestyle", "Lifestyle & Hobbies", "Cooking, travel, games and everyday interests."),
    Category("language", "Languages", "Language practice and translation."),
    Category("science", "Science & Research", "Researchers and science explainers."),
    Category("entertainment", "Entertainment", "Media, sports and fun."),
    Category("other", "Other", "Everything else."),
)
BY_SLUG = {category.slug: category for category in CATEGORIES}
SLUGS = tuple(BY_SLUG)


def get(slug: str | None) -> Category | None:
    return BY_SLUG.get(slug) if slug else None
