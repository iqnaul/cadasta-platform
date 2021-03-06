import re
from functools import partial
from django.conf import settings
from django.utils.translation import ugettext as _
from core.messages import SANITIZE_ERROR
from core.validators import sanitize_string
from .choices import QUESTION_TYPES, XFORM_GEOM_FIELDS
from .exceptions import InvalidQuestionnaire


def validate_accuracy(val):
    """Returns True if the provided value is a positive float. """

    # bool can be casted to float that's why we check this first
    if isinstance(val, bool):
        return False

    try:
        val = float(val)
        if val > 0:
            return True
    except ValueError:
        pass

    return False


def gps_relevant(json):
    return json.get('type') in XFORM_GEOM_FIELDS


def validate_id_string(json):
    id_string = json.get('id_string', '')
    if not id_string or re.search(r"\s", id_string):
        return _("'id_string' cannot be blank or contain whitespace.")


def validate_type(type, value):
    if type == 'string':
        return isinstance(value, str)
    elif type == 'number':
        return (not isinstance(value, bool) and
                isinstance(value, (int, float)))
    elif type == 'integer':
        return not isinstance(value, bool) and isinstance(value, int)
    elif type == 'boolean':
        return isinstance(value, bool)
    elif type == 'array':
        return isinstance(value, list)


QUESTIONNAIRE_SCHEMA = {
    'title': {'type': 'string', 'required': True},
    'id_string': {'type': 'string', 'required': True},
    'default_language': {'type': 'string',
                         'required': True,
                         'enum': settings.FORM_LANGS.keys()},
}

QUESTION_SCHEMA = {
    'name': {'type': 'string', 'required': True},
    'label': {'type': 'string'},
    'type': {'type': 'string',
             'required': True,
             'enum': [c[0] for c in QUESTION_TYPES]},
    'required': {'type': 'boolean'},
    'appearance': {'type': 'string'},
    'constraint': {'type': 'string'},
    'index': {'type': 'integer', 'required': True},
    'gps_accuracy': {'type': 'number',
                     'function': validate_accuracy,
                     'errors': {
                        'function': _("gps_accuracy must be positve float")
                     },
                     'relevant': gps_relevant}
}

QUESTION_GROUP_SCHEMA = {
    'name': {'type': 'string', 'required': True},
    'label': {'type': 'string'},
    'type': {'type': 'string', 'required': True},
    'index': {'type': 'integer', 'required': True}
}

QUESTION_OPTION_SCHEMA = {
    'name': {'type': 'string', 'required': True},
    'label': {'type': 'string', 'required': True},
    'index': {'type': 'integer', 'required': True}
}


def validate_schema(schema, json):
    errors = {}
    for key, reqs in schema.items():
        item_errors = []
        item = json.get(key, None)

        if reqs.get('relevant') and not reqs['relevant'](json):
            continue

        if reqs.get('required', False) and item is None:
            item_errors.append(_("This field is required."))
        elif item:

            if not validate_type(reqs.get('type'), item):
                item_errors.append(
                    _("Value must be of type {}.").format(reqs.get('type')))

            if reqs.get('enum') and item not in reqs.get('enum'):
                item_errors.append(
                    _("{} is not an accepted value.").format(item))

            if reqs.get('function') and not reqs['function'](item):
                error = _("Validator {} did not validate.").format(
                    reqs['function'].__name__)
                if reqs.get('errors') and reqs['errors'].get('function'):
                    error = reqs['errors']['function']
                item_errors.append(error)

            if not sanitize_string(item):
                item_errors.append(SANITIZE_ERROR)

        if item_errors:
            errors[key] = item_errors

    return errors


def validate_question_options(options):
    errors = []

    for option in options:
        errors.append(validate_schema(QUESTION_OPTION_SCHEMA, option))

    return errors


def validate_questions(questions):
    errors = []

    for question in questions:
        question_errs = validate_schema(QUESTION_SCHEMA, question)
        option_errs = validate_question_options(question.get('options', []))

        if any([o for o in option_errs]):
            question_errs['options'] = option_errs
        errors.append(question_errs)

    return errors


def validate_question_groups(groups):
    errors = []

    for group in groups:
        group_errs = validate_schema(QUESTION_GROUP_SCHEMA, group)

        questions_errs = validate_questions(group.get('questions', []))
        if any([q for q in questions_errs]):
            group_errs['questions'] = questions_errs

        questions_group_errs = validate_question_groups(
            group.get('question_groups', []))
        if any([q for q in questions_group_errs]):
            group_errs['question_groups'] = questions_group_errs

        errors.append(group_errs)

    return errors


def validate_questionnaire(json):

    errors = validate_schema(QUESTIONNAIRE_SCHEMA, json)

    if not errors.get('id_string'):
        id_errors = validate_id_string(json)
        if id_errors:
            errors['id_string'] = id_errors

    question_errs = validate_questions(json.get('questions', []))
    if any([q for q in question_errs]):
        errors['questions'] = question_errs

    group_errs = validate_question_groups(json.get('question_groups', []))
    if any([q for q in group_errs]):
        errors['question_groups'] = group_errs

    if errors:
        return errors


required_fields = {'location_type': 'select one',
                   'party_name': 'text',
                   'party_type': 'select one',
                   'tenure_type': 'select one'}
geometry_fields = {'location_geoshape': 'geoshape',
                   'location_geotrace': 'geotrace',
                   'location_geometry': 'geopoint'}


def is_required(bind):
    """
    Checks if a field is required.

    Args:
        bind: dict containing the field's bind property

    Returns:
        `True` if `bind` is defined and bind['required'] == 'yes
    """
    return bind is not None and bind.get('required') == 'yes'


def map_fields(fields):
    """
    Extracts the neccessary info needed to validate fields.

    Args:
        fields: All required and geometry fields defined in the questionnaire.

    Returns:
        dict containing all fields with their type and required status as
        defined in the questionnaire. Each element in the dict has the
        structure `fieldname: (type, required, choices)`
    """
    return {field.get('name'): (field.get('type'),
                                is_required(field.get('bind')),
                                field.get('choices'))
            for field in fields}


def validate_party_types(choices):
    if choices is None:
        return False

    return {c.get('name') for c in choices} == {'IN', 'GR', 'CO'}


def validate_field(field_def, available_fields, field):
    """
    Validates a field against a field definition.

    Args:
        field_def: Field definition, the field is validated against.
        available_fields: Fields defined in the questionnaire.
        field: string containting the field name

    Returns:
        string containing the error message if a criteria is not met.
    """
    # Check if the field is defined
    if field not in available_fields.keys():
        return _('Field {} is required.').format(field)

    # Check if the field has the correct type
    if not available_fields[field][0] == field_def[field]:
        return _('Field {} must be of type {}.').format(
            field, field_def[field])

    # Check if the field is defined as required.
    if not available_fields[field][1]:
        return _('Field {} must be required.').format(field)

    if (field == 'party_type' and
            not validate_party_types(available_fields[field][2])):
        return _('Field party_type must have choices "IN", "GR", "CO"')


def validate_required(all_fields):
    # Required fields can be inside repeat groups so we're getting all children
    # from repeat groups and attaching them to the highest level in the dict
    repeat_groups = [f for f in all_fields if (f.get('type') == 'repeat')]
    repeat_children = []
    for group in repeat_groups:
        repeat_children += group.get('children', [])
    all_fields = all_fields + repeat_children

    # Getting all required fields defined in the questionnaire
    fields = list(required_fields.keys()) + list(geometry_fields.keys())
    required_available = (f for f in all_fields if f.get('name') in fields)
    required_available = map_fields(required_available)

    # Getting all geometry fields defined in the questionnaire
    geometries = (f for f in all_fields if f.get('name') in geometry_fields)
    geometries = map_fields(geometries)

    # Validating all required fields
    _validate_required = partial(validate_field,
                                 required_fields,
                                 required_available)
    required_errors = [_validate_required(f) for f in required_fields]

    # Validating all geometry fields. This is a separate action because only
    # one of the three possible must be defined. We're basically just checking
    # if the geometries that are defined are ok.
    _validate_geometries = partial(validate_field,
                                   geometry_fields,
                                   required_available)
    geometry_errors = [_validate_geometries(g) for g in geometries]

    # joining both error lists
    errors = required_errors + geometry_errors

    # One geometry must be defined, so we're checking that here.
    if not len(geometries) > 0:
        errors.append(_('Please provide at least one geometry field.'))

    errors = [e for e in errors if e]
    if errors:
        raise InvalidQuestionnaire(errors)
