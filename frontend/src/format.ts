export const pct = (x: number) => `${(x * 100).toFixed(1)}%`;

export const FIELD_LABEL: Record<string, string> = {
  first_name: "First name",
  last_name: "Last name",
  email: "Email",
  phone: "Phone",
  company: "Company",
  street: "Street",
  city: "City",
  region: "Region",
  postal_code: "Postal code",
  country: "Country",
};

export const DISPLAY_FIELDS = [
  "first_name",
  "last_name",
  "email",
  "phone",
  "company",
  "street",
  "city",
  "postal_code",
] as const;
