from typing import Dict, List
from enum import Enum


class RequirementsMismatchException(Exception):
    pass


class Requirements:
    i = 0
    """
    A utility class which enables adding and checking requirements for Pipelines.

    The class contains two subclasses for enum values which are used in the functions.
    """

    class Level(Enum):
        MANDATORY = 1
        OPTIONAL = 2

    class Kind(Enum):
        PROVIDED = 1
        EXPECTED = 2

    def __init__(self, kind: "Requirements.Kind", name: str = "ANONYMOUS-"):
        """
        The constructor for a requirements object.
        
        :param kind: The :class:`Requirements.Kind` of the requirements
        :param name: A name which can be set to make warning diagnostics simpler to understand
        """
        self.kind = kind
        self.reqs: Dict[str, Requirements.Level] = dict()
        if name == "ANONYMOUS-":
            name = name + str(Requirements.i)
        self.name = name
        Requirements.i += 1

    def add_requirement(self, key: str, level: "Requirements.Level" = Level.MANDATORY):
        """
        A function to add requirements to this requirement object.

        To specify an optional requirement for:
        [
            {
                "signature": {
                    "name" : --The entry which is required--
                }
            }
        ]
        One has to use addRequirement("signature.name", :class:`Requirements.Level`.OPTIONAL)

        :param key: The name of the requirement, if necessary hierarchically separated by dots
        :param level: The level the requirement has, is it mandatory or optional (defaults to mandatory)

        :return: This object, so requirements can be daisy-chained
        """
        self.reqs[key] = level
        return self

    def set_name(self, name):
        """
        Sets the name for this requirements object.

        :param name: The name to set
        """

    def clear(self):
        """
        Clears the requirements
        """
        self.reqs = dict()

    def fulfills(self, other: "Requirements"):
        """
        Checks if the provided requirements fulfill the expected requirements.

        Prints a list of warnings for requirement level mismatches    

        :param other: The requirements to compare against

        :raise RequirementsMismatchException: If both requirements are of the same :class:`Requirements.Kind`
            OR If any :class:`Requirements.Level`.MANDATORY requirements were not fulfilled

        :return: True if all requirements expected are fulfilled
        """
        if other.kind == self.kind:
            raise RequirementsMismatchException("Both Requirements were of kind "
                                                + ("provided" if self.kind == Requirements.Kind.PROVIDED
                                                   else "expected")
                                                + ", you probably wanted to use self.merge() instead!")
        if self.kind == Requirements.Kind.EXPECTED:
            return other.fulfills(self)
        
        if "all" in self.reqs:
            return True

        warnings = []
        errors = []
        for key in other.reqs:
            if other.reqs[key] == Requirements.Level.MANDATORY:
                if key in self.reqs:
                    if other.reqs[key] != self.reqs[key]:
                        warnings.append(key)
                else:
                    errors.append(key)
        print(self.name + ": Keys " + str(warnings) + " were optionally provided but are mandatory")
        if errors:
            raise RequirementsMismatchException(str(errors))
        return not errors

    def verify(self, data: List[dict]):
        """
        Checks if the data seems to fulfill the requirements.

        If the requirements contain 'all', they will NOT be verified

        :param data: The dictionary on which the requirements are supposed to hold
        
        :raise RequirementsMismatchException: If any :class:`Requirements.Level`.MANDATORY requirements were not fulfilled

        :return: True if all mandatory requirements are fulfilled (e.g., the key exists)
        """
        errors = set()
        if "all" in self.reqs:
            print(self.name + ": Explicitly cannot verify if 'all' requirements are fulfilled.")
            return True
        for key in self.reqs:
            components = key.split(".")
            for entry in data:
                value = entry
                for component in components:
                    try:
                        if component in value:
                            value = value[component]
                        elif self.reqs[key] == Requirements.Level.MANDATORY:
                            errors.add(key)
                    except:
                        if self.reqs[key] == Requirements.Level.MANDATORY:
                            errors.add(key)
        if errors:
            raise RequirementsMismatchException("Keys " + str(errors) + " were mandatory, but are (sometimes) missing.")
        return True

    def merge(self, other: "Requirements"):
        """
        Merges two requirements.

        :param other: The requirements to merge with

        :raise RequirementsMismatchException: If both requirements are of a different :class:`Requirements.Kind`

        :return: Returns a NEW Requirements object containing the merge result
        """
        if other.kind != self.kind:
            raise RequirementsMismatchException("Both Requirements were of different kinds"
                                                + ", you probably wanted to use self.fulfills() instead!")

        r = Requirements(self.kind, "merged-" + self.name)
        # Iterate over symmetric difference and add all keys
        for key in self.reqs.keys() ^ other.reqs.keys():
            if key in self.reqs:
                r.add_requirement(key, self.reqs[key])
            else:
                r.add_requirement(key, other.reqs[key])
        
        # Iterate over intersection and add key according to kind
        for key in self.reqs.keys() & other.reqs.keys():
            if self.reqs[key] != other.reqs[key]:
                level = Requirements.Level.MANDATORY
            else:
                level = self.reqs[key]
            r.add_requirement(key, level)

        return r
