#!/usr/bin/python
##Copyright 2008-2019 Thomas Paviot (tpaviot@gmail.com)

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

###########
# imports #
###########
import configparser
import datetime
import glob
import keyword  # to prevent using python language keywords
import logging
from operator import itemgetter
import os
import os.path
import platform
import re
import subprocess
import sys
import time

from Modules import *

import CppHeaderParser

##############################################
# Load configuration file and setup settings #
##############################################
config = configparser.ConfigParser()
config.read('wrapper_generator.conf')
# pythonocc version
PYTHONOCC_VERSION = config.get('pythonocc-core', 'version')
# oce headers location
OCE_INCLUDE_DIR = config.get('OCE', 'include_dir')
if not os.path.isdir(OCE_INCLUDE_DIR):
    raise AssertionError("OCE include dir %s not found." % OCE_INCLUDE_DIR)
# swig output path
PYTHONOCC_CORE_PATH = config.get('pythonocc-core', 'path')
SWIG_OUTPUT_PATH = os.path.join(PYTHONOCC_CORE_PATH, 'src', 'SWIG_files', 'wrapper')
HEADERS_OUTPUT_PATH = os.path.join(PYTHONOCC_CORE_PATH, 'src', 'SWIG_files', 'headers')

GENERATE_SWIG_FILES = False  # if set to False, skip .i generator, to avoid recompile everything

###################################################
# Set logger, to log both to a file and to stdout #
# code from https://stackoverflow.com/questions/13733552/logger-configuration-to-log-to-file-and-print-to-stdout
###################################################
log_formatter = logging.Formatter("[%(levelname)-5.5s]  %(message)s")
log = logging.getLogger()
log.setLevel(logging.INFO)
log_file_name = os.path.join(SWIG_OUTPUT_PATH, 'generator.log')
# ensure log file is emptied before running the generator
lf = open(log_file_name, 'w')
lf.close()

file_handler = logging.FileHandler(log_file_name)
file_handler.setFormatter(log_formatter)
log.addHandler(file_handler)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)
log.addHandler(console_handler)

####################
# Global variables #
####################

##################
# For statistics #
##################
NB_TOTAL_CLASSES = 0  # number of wrapped classes
NB_TOTAL_METHODS = 0  # number of wrapped methods

ALL_TOOLKITS = [TOOLKIT_Foundation,
                TOOLKIT_Modeling,
                TOOLKIT_Visualisation,
                TOOLKIT_DataExchange,
                TOOLKIT_OCAF,
                TOOLKIT_VTK]
TOOLKITS = {}
for tk in ALL_TOOLKITS:
    TOOLKITS.update(tk)

LICENSE_HEADER = """/*
Copyright 2008-2020 Thomas Paviot (tpaviot@gmail.com)

This file is part of pythonOCC.
pythonOCC is free software: you can redistribute it and/or modify
it under the terms of the GNU Lesser General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

pythonOCC is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public License
along with pythonOCC.  If not, see <http://www.gnu.org/licenses/>.
*/
"""

# check if SWIG_OUTPUT_PATH exists, otherwise create it
if not os.path.isdir(SWIG_OUTPUT_PATH):
    os.mkdir(SWIG_OUTPUT_PATH)

# the following var is set when the module
# is created
CURRENT_MODULE = None
CURRENT_MODULE_PYI_STATIC_METHODS_ALIASES = ""

PYTHON_MODULE_DEPENDENCY = []
HEADER_DEPENDENCY = []

# remove headers that can't be parse by CppHeaderParser
HXX_TO_EXCLUDE_FROM_CPPPARSER = ['NCollection_StlIterator.hxx',
                                 'NCollection_CellFilter.hxx',
                                 'Standard_CLocaleSentry.hxx',
                                 'TColStd_PackedMapOfInteger.hxx',
                                 # this file has to be fixed
                                 # there's a missing include
                                 'Aspect_VKeySet.hxx',
                                 'TPrsStd_AISPresentation.hxx',
                                 'TPrsStd_AISViewer.hxx',
                                 'StepToTopoDS_Tool.hxx',
                                 'AIS_DataMapOfSelStat.hxx',
                                 'BVH_IndexedBoxSet.hxx',
                                 'AIS_Axis.hxx',
                                 'BRepApprox_SurfaceTool.hxx',
                                 'BRepBlend_BlendTool.hxx',
                                 'BRepBlend_HCurveTool.hxx',
                                 'BRepBlend_HCurve2dTool.hxx',
                                 'IntWalk_PWalking.hxx',
                                 'HLRAlgo_PolyHidingData.hxx',
                                 'HLRAlgo_Array1OfPHDat.hxx',
                                 'Standard_Dump.hxx',  # to avoid a dependency of Standard over TCollection
                                 'IMeshData_ParametersListArrayAdaptor.hxx',
                                 'BRepMesh_CustomBaseMeshAlgo.hxx',
                                 'BRepMesh_CylinderRangeSplitter.hxx',
                                 'BRepMesh_DefaultRangeSplitter.hxx',
                                 'BRepMesh_BoundaryParamsRangeSplitter.hxx',
                                 'BRepMesh_ConeRangeSplitter.hxx',
                                 'BRepMesh_NURBSRangeSplitter.hxx',
                                 'BRepMesh_SphereRangeSplitter.hxx',
                                 'BRepMesh_TorusRangeSplitter.hxx',
                                 'BRepMesh_UVParamRangeSplitter.hxx',
                                 'AdvApp2Var_Data_f2c.hxx',
                                 'Convert_CosAndSinEvalFunction.hxx'  # strange, a method in a typedef, confusing
                                 ]

# some includes fail at being compiled
HXX_TO_EXCLUDE_FROM_BEING_INCLUDED = ['AIS_DataMapOfSelStat.hxx', # TODO : report the bug upstream
                                      # same for the following
                                      'AIS_DataMapIteratorOfDataMapOfSelStat.hxx',
                                      # file has to be fixed, missing include
                                      'NCollection_CellFilter.hxx',
                                      'Aspect_VKeySet.hxx',
                                      'TPrsStd_AISPresentation.hxx',
                                      'Interface_ValueInterpret.hxx',
                                      'TPrsStd_AISViewer.hxx',
                                      'StepToTopoDS_Tool.hxx',
                                      'BVH_IndexedBoxSet.hxx',
                                      'AIS_Axis.hxx',
                                      # report the 3 following to upstream, buggy
                                      # error: ‘ChFiDS_ChamfMode’ does not name a type;
                                      'ChFiKPart_ComputeData_ChPlnPln.hxx',
                                      'ChFiKPart_ComputeData_ChPlnCyl.hxx',
                                      'ChFiKPart_ComputeData_ChPlnCon.hxx',
                                      # others
                                      'BRepApprox_SurfaceTool.hxx',
                                      'BRepBlend_BlendTool.hxx',
                                      'BRepBlend_HCurveTool.hxx',
                                      'BRepBlend_HCurve2dTool.hxx',
                                      'IntWalk_PWalking.hxx',
                                      'HLRAlgo_PolyHidingData.hxx',
                                      'HLRAlgo_Array1OfPHDat.hxx',
                                      'ShapeUpgrade_UnifySameDomain.hxx',
                                      'IMeshData_ParametersListArrayAdaptor.hxx',
                                      'BRepMesh_CustomBaseMeshAlgo.hxx',
                                      'BRepMesh_CylinderRangeSplitter.hxx',
                                      'BRepMesh_DefaultRangeSplitter.hxx',
                                      'BRepMesh_BoundaryParamsRangeSplitter.hxx',
                                      'BRepMesh_ConeRangeSplitter.hxx',
                                      'BRepMesh_NURBSRangeSplitter.hxx',
                                      'BRepMesh_SphereRangeSplitter.hxx',
                                      'BRepMesh_TorusRangeSplitter.hxx',
                                      'BRepMesh_UVParamRangeSplitter.hxx'
                                      ]

# some typedefs parsed by CppHeader can't be wrapped
# and generate SWIG syntax errors. We just forget
# about wrapping those typedefs
TYPEDEF_TO_EXCLUDE = ['Handle_Standard_Transient',
                      'NCollection_DelMapNode',
                      'BOPDS_DataMapOfPaveBlockCommonBlock',
                      # BOPCol following templates are already wrapped in TColStd
                      # which causes issues with SWIg
                      'BOPCol_MapOfInteger', 'BOPCol_SequenceOfReal', 'BOPCol_DataMapOfIntegerInteger',
                      'BOPCol_DataMapOfIntegerReal', 'BOPCol_IndexedMapOfInteger', 'BOPCol_ListOfInteger',
                      'IntWalk_VectorOfWalkingData',
                      'IntWalk_VectorOfInteger',
                      'TopoDS_AlertWithShape',
                      'gp_TrsfNLerp',
                      'TopOpeBRepTool_IndexedDataMapOfSolidClassifier',
                      #
                      'Graphic3d_Vec2u',
                      'Graphic3d_Vec3u',
                      'Graphic3d_Vec4u',
                      'Select3D_BndBox3d',
                      'SelectMgr_TriangFrustums',
                      'SelectMgr_TriangFrustumsIter',
                      'SelectMgr_MapOfObjectSensitives',
                      'Graphic3d_IndexedMapOfAddress',
                      'Graphic3d_MapOfObject',
                      'Storage_PArray',
                      'Interface_StaticSatisfies',
                      'IMeshData::ICurveArrayAdaptor'
                     ]

# Following are standard integer typedefs. They have to be replaced
# with int, in the function adapt_param_type
STANDARD_INTEGER_TYPEDEF = ["Graphic3d_ArrayFlags", "Graphic3d_ZLayerId",
                            "MeshVS_BuilderPriority", "MeshVS_BuilderPriority",
                            "MeshVS_DisplayModeFlags", "XCAFPrs_DocumentExplorerFlags"]
# The list of all enums defined in oce
ALL_ENUMS = []

# HArray1 apperead in occt 7x
# They are a kind of collection defined in NCollection_DefineHArray1
# a macro define this kind of object
ALL_HARRAY1 = {}
# same for NCollection_DefineHarray2
ALL_HARRAY2 = {}
# same for NCollection_DefineHSequence
ALL_HSEQUENCE = {}

# the list of all handles defined by the
# DEFINE_STANDARD_HANDLE occ macro
ALL_STANDARD_HANDLES = []

# the list of al classes that inherit from Standard_Transient
# and, as a consequence, need the %wrap_handle and %make_alias macros
ALL_STANDARD_TRANSIENTS = ['Standard_Transient']

# classes that must not wrap a default constructor
NODEFAULTCTOR = ['IFSelect_SelectBase', 'IFSelect_SelectControl', 'IFSelect_SelectDeduct',
                 'PCDM_RetrievalDriver', 'MeshVS_DataSource3D', 'AIS_Dimension', 'Graphic3d_Layer',
                 'Expr_BinaryExpression', 'Expr_NamedExpression', 'Expr_UnaryExpression',
                 'Expr_SingleExpression', 'Expr_SingleRelation', 'Expr_UnaryExpression',
                 'Geom_SweptSurface', 'Geom_BoundedSurface', 'ShapeCustom_Modification',
                 'SelectMgr_CompositionFilter',
                 'BRepMeshData_Wire', 'BRepMeshData_PCurve', 'BRepMeshData_Face',
                 'BRepMeshData_Edge', 'BRepMeshData_Curve',
                 'Graphic3d_BvhCStructureSet' ## Windows specific
                 ]


TEMPLATES_TO_EXCLUDE = ['gp_TrsfNLerp',
                        # IntPolyh templates don't work
                        'IntPolyh_Array',
                        # and this one also
                        'NCollection_CellFilter',
                        'BVH_PrimitiveSet',
                        'BVH_Builder',
                        'pair',  # for std::pair
                        # for Graphic3d to compile
                        'Graphic3d_UniformValue',
                        'NCollection_Shared',
                        'NCollection_Handle',
                        'NCollection_DelMapNode'
                        'BOPTools_BoxSet',
                        'BOPTools_PairSelector',
                        'BOPTools_BoxSet',
                        'BOPTools_BoxSelector',
                        'BOPTools_PairSelector'
                        ]

##########################
# Templates for includes #
##########################

BOPDS_HEADER_TEMPLATE = '''
%include "BOPCol_NCVector.hxx";
'''

INTPOLYH_HEADER_TEMPLATE = '''
%include "IntPolyh_Array.hxx";
%include "IntPolyh_ArrayOfTriangles.hxx";
%include "IntPolyh_SeqOfStartPoints.hxx";
%include "IntPolyh_ArrayOfEdges.hxx";
%include "IntPolyh_ArrayOfTangentZones.hxx";
%include "IntPolyh_ArrayOfSectionLines.hxx";
%include "IntPolyh_ListOfCouples.hxx";
%include "IntPolyh_ArrayOfPoints.hxx";
'''

BVH_HEADER_TEMPLATE = '''
%include "BVH_Box.hxx";
%include "BVH_PrimitiveSet.hxx";
'''

PRS3D_HEADER_TEMPLATE = '''
%include "Prs3d_Point.hxx";
'''

BREPALGOAPI_HEADER = '''
%include "BRepAlgoAPI_Algo.hxx";
'''

GRAPHIC3D_DEFINE_HEADER = '''
%define Handle_Graphic3d_TextureSet Handle(Graphic3d_TextureSet)
%enddef
%define Handle_Aspect_DisplayConnection Handle(Aspect_DisplayConnection)
%enddef
%define Handle_Graphic3d_NMapOfTransient Handle(Graphic3d_NMapOfTransient)
%enddef
'''

NCOLLECTION_HEADER_TEMPLATE = '''
%include "NCollection_TypeDef.hxx";
%include "NCollection_Array1.hxx";
%include "NCollection_Array2.hxx";
%include "NCollection_Map.hxx";
%include "NCollection_DefaultHasher.hxx";
%include "NCollection_List.hxx";
%include "NCollection_Sequence.hxx";
%include "NCollection_DataMap.hxx";
%include "NCollection_IndexedMap.hxx";
%include "NCollection_IndexedDataMap.hxx";
%include "NCollection_DoubleMap.hxx";
%include "NCollection_DefineAlloc.hxx";
%include "Standard_Macro.hxx";
%include "Standard_DefineAlloc.hxx";
%include "NCollection_UBTree.hxx";
%include "NCollection_UBTreeFiller.hxx";
%include "NCollection_Lerp.hxx";
%include "NCollection_Vector.hxx";
%include "NCollection_Vec2.hxx";
%include "NCollection_Vec3.hxx";
%include "NCollection_Vec4.hxx";
%include "NCollection_Mat4.hxx";
%include "NCollection_TListIterator.hxx";
%include "NCollection_UtfString.hxx";
%include "NCollection_UtfIterator.hxx";
%include "NCollection_SparseArray.hxx";

%ignore NCollection_List::First();
%ignore NCollection_List::Last();
%ignore NCollection_TListIterator::Value();
'''

################################
# Templates for method wrapper #
################################

HARRAY1_TEMPLATE = """
class HClassName : public _Array1Type_, public Standard_Transient {
  public:
    HClassName(const Standard_Integer theLower, const Standard_Integer theUpper);
    HClassName(const Standard_Integer theLower, const Standard_Integer theUpper, const _Array1Type_::value_type& theValue);
    HClassName(const _Array1Type_& theOther);
    const _Array1Type_& Array1();
    _Array1Type_& ChangeArray1();
};
%make_alias(HClassName)

"""

HARRAY1_TEMPLATE_PYI = """
class HClassName(_Array1Type_, Standard_Transient):
    def __init__(self, theLower: int, theUpper: int) -> None: ...
    def Array1(self) -> _Array1Type_: ...

"""

HARRAY2_TEMPLATE = """
class HClassName : public _Array2Type_, public Standard_Transient {
  public:
    HClassName(const Standard_Integer theRowLow, const Standard_Integer theRowUpp, const Standard_Integer theColLow,
                const Standard_Integer theColUpp);
    HClassName(const Standard_Integer theRowLow, const Standard_Integer theRowUpp, const Standard_Integer theColLow,
               const Standard_Integer theColUpp, const _Array2Type_::value_type& theValue);
    HClassName(const _Array2Type_& theOther);
    const _Array2Type_& Array2 ();
    _Array2Type_& ChangeArray2 (); 
};
%make_alias(HClassName)

"""

HARRAY2_TEMPLATE_PYI = """
class HClassName(_Array2Type_, Standard_Transient):
    @overload
    def __init__(self, theRowLow: int, theRowUpp: int, theColLow: int, theColUpp: int) -> None: ...
    @overload
    def __init__(self, theOther: _Array2Type_) -> None: ...
    def Array2(self) -> _Array2Type_: ...

"""

HSEQUENCE_TEMPLATE = """
class HClassName : public _SequenceType_, public Standard_Transient {
  public:
    HClassName();
    HClassName(const _SequenceType_& theOther);
    const _SequenceType_& Sequence();
    void Append (const _SequenceType_::value_type& theItem);
    void Append (_SequenceType_& theSequence);
    _SequenceType_& ChangeSequence();
};
%make_alias(HClassName)

"""

HSEQUENCE_TEMPLATE_PYI = """
class HClassName(_SequenceType_, Standard_Transient):
    @overload
    def __init__(self) -> None: ...
    @overload
    def __init__(self, other: _SequenceType_) -> None: ...
    def Sequence(self) -> _SequenceType_: ...
    def Append(self, theSequence: _SequenceType_) -> None: ...

"""

NCOLLECTION_ARRAY1_EXTEND_TEMPLATE = '''
%extend NCollection_Array1_Template_Instanciation {
    %pythoncode {
    def __getitem__(self, index):
        if index + self.Lower() > self.Upper():
            raise IndexError("index out of range")
        else:
            return self.Value(index + self.Lower())

    def __setitem__(self, index, value):
        if index + self.Lower() > self.Upper():
            raise IndexError("index out of range")
        else:
            self.SetValue(index + self.Lower(), value)

    def __len__(self):
        return self.Length()

    def __iter__(self):
        self.low = self.Lower()
        self.up = self.Upper()
        self.current = self.Lower() - 1
        return self

    def next(self):
        if self.current >= self.Upper():
            raise StopIteration
        else:
            self.current += 1
        return self.Value(self.current)

    __next__ = next
    }
};
'''

# the related pyi stub string
NCOLLECTION_ARRAY1_EXTEND_TEMPLATE_PYI = '''
class NCollection_Array1_Template_Instanciation:
    @overload
    def __init__(self) -> None: ...
    @overload
    def __init__(self, theLower: int, theUpper: int) -> None: ...
    def __getitem__(self, index: int) -> Type_T: ...
    def __setitem__(self, index: int, value: Type_T) -> None: ...
    def __len__(self) -> int: ...
    def __iter__(self) -> Iterator[Type_T]: ...
    def next(self) -> Type_T: ...
    __next__ = next
    def Init(self, theValue: Type_T) -> None: ...
    def Size(self) -> int: ...
    def Length(self) -> int: ...
    def IsEmpty(self) -> bool: ...
    def Lower(self) -> int: ...
    def Upper(self) -> int: ...
    def IsDetectable(self) -> bool: ...
    def IsAllocated(self) -> bool: ...
    def First(self) -> Type_T: ...
    def Last(self) -> Type_T: ...
    def Value(self, theIndex: int) -> Type_T: ...
    def SetValue(self, theIndex: int, theValue: Type_T) -> None: ...
'''


NCOLLECTION_LIST_EXTEND_TEMPLATE = '''
%extend NCollection_List_Template_Instanciation {
    %pythoncode {
    def __len__(self):
        return self.Size()
    }
};
'''

# the related pyi stub string
NCOLLECTION_LIST_EXTEND_TEMPLATE_PYI = '''
class NCollection_List_Template_Instanciation:
    def __init__(self) -> None: ...
    def __len__(self) -> int: ...
    def Size(self) -> int: ...
    def Clear(self) -> None: ...
    def First(self) -> Type_T: ...
    def Last(self) -> Type_T: ...
    def Append(self, theItem: Type_T) -> Type_T: ...
    def Prepend(self, theItem: Type_T) -> Type_T: ...
    def RemoveFirst(self) -> None: ...
    def Reverse(self) -> None: ...
    def Value(self, theIndex: int) -> Type_T: ...
    def SetValue(self, theIndex: int, theValue: Type_T) -> None: ...
'''

# NCollection_Sequence and NCollection_List shares the
# same pyi and extension templates. It's just a copy/paste
# from the previous templates, it may change in the future
NCOLLECTION_SEQUENCE_EXTEND_TEMPLATE = '''
%extend NCollection_Sequence_Template_Instanciation {
    %pythoncode {
    def __len__(self):
        return self.Size()
    }
};
'''

# the related pyi stub string
NCOLLECTION_SEQUENCE_EXTEND_TEMPLATE_PYI = '''
class NCollection_Sequence_Template_Instanciation:
    def __init__(self) -> None: ...
    def __len__(self) -> int: ...
    def Size(self) -> int: ...
    def Clear(self) -> None: ...
    def First(self) -> Type_T: ...
    def Last(self) -> Type_T: ...
    def Length(self) -> int: ...
    def Append(self, theItem: Type_T) -> Type_T: ...
    def Prepend(self, theItem: Type_T) -> Type_T: ...
    def RemoveFirst(self) -> None: ...
    def Reverse(self) -> None: ...
    def Value(self, theIndex: int) -> Type_T: ...
    def SetValue(self, theIndex: int, theValue: Type_T) -> None: ...
'''
# We extend the NCollection_DataMap template with a Keys
# method that returns a list of Keys
# TODO: do the same for other Key types
NCOLLECTION_DATAMAP_EXTEND_TEMPLATE = '''
%extend NCollection_DataMap_Template_Instanciation {
    PyObject* Keys() {
        PyObject *l=PyList_New(0);
        for (NCollection_DataMap_Template_Name::Iterator anIt1(*self); anIt1.More(); anIt1.Next()) {
          PyObject *o = PyLong_FromLong(anIt1.Key());
          PyList_Append(l, o);
          Py_DECREF(o);
        }
    return l;
    }
};
'''

TEMPLATE__EQ__ = """
            %%extend{
                bool __eq_wrapper__(%s other) {
                if (*self==other) return true;
                else return false;
                }
            }
            %%pythoncode {
            def __eq__(self, right):
                try:
                    return self.__eq_wrapper__(right)
                except:
                    return False
            }
"""

TEMPLATE__IMUL__ = """
            %%extend{
                void __imul_wrapper__(%s other) {
                *self *= other;
                }
            }
            %%pythoncode {
            def __imul__(self, right):
                self.__imul_wrapper__(right)
                return self
            }
"""

TEMPLATE__NE__ = """
            %%extend{
                bool __ne_wrapper__(%s other) {
                if (*self!=other) return true;
                else return false;
                }
            }
            %%pythoncode {
            def __ne__(self, right):
                try:
                    return self.__ne_wrapper__(right)
                except:
                    return True
            }
"""

TEMPLATE__IADD__ = """
            %%extend{
                void __iadd_wrapper__(%s other) {
                *self += other;
                }
            }
            %%pythoncode {
            def __iadd__(self, right):
                self.__iadd_wrapper__(right)
                return self
            }
"""

TEMPLATE__ISUB__ = """
            %%extend{
                void __isub_wrapper__(%s other) {
                *self -= other;
                }
            }
            %%pythoncode {
            def __isub__(self, right):
                self.__isub_wrapper__(right)
                return self
            }
"""

TEMPLATE__ITRUEDIV__ = """
            %%extend{
                void __itruediv_wrapper__(%s other) {
                *self /= other;
                }
            }
            %%pythoncode {
            def __itruediv__(self, right):
                self.__itruediv_wrapper__(right)
                return self
            }
"""

TEMPLATE_OSTREAM = """
        %%feature("autodoc", "1");
        %%extend{
            std::string %sToString() {
            std::stringstream s;
            self->%s(s);
            return s.str();}
        };
"""

TEMPLATE_ISTREAM = """
            %%feature("autodoc", "1");
            %%extend{
                void %sFromString(std::string src) {
                std::stringstream s(src);
                self->%s(s);}
            };
"""

TEMPLATE_DUMPJSON = """
            %feature("autodoc", "1");
            %extend{
                std::string DumpJsonToString(int depth=-1) {
                std::stringstream s;
                self->DumpJson(s, depth);
                return s.str();}
            };
"""

TEMPLATE_GETTER_SETTER = """
        %%feature("autodoc","1");
        %%extend {
            %s Get%s(%s) {
            return (%s) $self->%s(%s);
            }
        };
        %%feature("autodoc","1");
        %%extend {
            void Set%s(%s) {
            $self->%s(%s)=value;
            }
        };
"""

TEMPLATE_HASHCODE = """
        %extend {
            Standard_Integer __hash__() {
            return $self->HashCode(2147483647);
            }
        };
"""

TIMESTAMP_TEMPLATE = """
############################
Running pythonocc-generator.
############################
git revision : %s

operating system : %s

occt version targeted : %s

date : %s
############################
"""

WIN_PRAGMAS = """
%{
#ifdef WNT
#pragma warning(disable : 4716)
#endif
%}

"""

def get_log_header():
    """ returns a header to be appended to the SWIG file
    Useful for development
    """
    os_name = platform.system() + ' ' + platform.architecture()[0] + ' ' + platform.release()
    generator_git_revision = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD']).strip().decode('utf8')
    now = str(datetime.datetime.now())
    # find the OCC VERSION targeted by the wrapper
    # the OCCT version is available from the Standard_Version.hxx header
    # e.g. define OCC_VERSION_COMPLETE     "7.4.0"
    standard_version_header = os.path.join(OCE_INCLUDE_DIR, "Standard_Version.hxx")
    occ_version = "unknown"
    if os.path.isfile(standard_version_header):
        with open(standard_version_header, 'r') as f:
            file_lines = f.readlines()
        for l in file_lines:
            if l.startswith("#define OCC_VERSION_COMPLETE"):
                occ_version = l.split('"')[1].strip()
    timestamp = TIMESTAMP_TEMPLATE % (generator_git_revision, os_name, occ_version, now)
    return timestamp


def get_log_footer(total_time):
    footer = """
#################################################
SWIG interface file generation completed in {:.2f}s
#################################################
""".format(total_time)
    return footer


def reset_header_depency():
    global HEADER_DEPENDENCY
    HEADER_DEPENDENCY = ['TColgp', 'TColStd', 'TCollection', 'Storage']


def check_is_persistent(class_name):
    """
    Checks, whether a class belongs to the persistent classes (and not to the transient ones)
    """
    for occ_module in ['PFunction', 'PDataStd', 'PPrsStd', 'PDF',
                       'PDocStd', 'PDataXtd', 'PNaming', 'PCDM_Document']:
        if class_name.startswith(occ_module):
            return True
    return False


def filter_header_list(header_list, exclusion_list):
    """ From a header list, remove hxx to HXX_TO_EXCLUDE
    The files to be excluded is specificed in the exlusion list
    """
    for header_to_remove in exclusion_list:
        if os.path.join(OCE_INCLUDE_DIR, header_to_remove) in header_list:
            header_list.remove(os.path.join(OCE_INCLUDE_DIR, header_to_remove))
    # remove platform dependent files
    # this is done to have the same SWIG files on every platform
    # wnt specific
    header_list = [x for x in header_list if not 'WNT' in x.lower()]
    header_list = [x for x in header_list if not 'wnt' in x.lower()]
    # linux
    header_list = [x for x in header_list if not 'X11' in x]
    header_list = [x for x in header_list if not 'XWD' in x]
    # and osx
    header_list = [x for x in header_list if not 'Cocoa' in x]
    return header_list


def test_filter_header_list():
    if sys.platform != 'win32':
        assert filter_header_list(['something', 'somethingWNT'], HXX_TO_EXCLUDE_FROM_CPPPARSER) == ['something']


def case_sensitive_glob(wildcard):
    """
    Case sensitive glob for Windows.
    Designed for handling of GEOM and Geom modules
    This function makes the difference between GEOM_* and Geom_* under Windows
    """
    flist = glob.glob(wildcard)
    pattern = wildcard.split('*')[0]
    f = []
    for file_ in flist:
        if pattern in file_:
            f.append(file_)
    return f


def get_all_module_headers(module_name):
    """ Returns a list with all header names
    """
    mh = case_sensitive_glob(os.path.join(OCE_INCLUDE_DIR, '%s.hxx' % module_name))
    mh += case_sensitive_glob(os.path.join(OCE_INCLUDE_DIR, '%s_*.hxx' % module_name))
    mh = filter_header_list(mh, HXX_TO_EXCLUDE_FROM_BEING_INCLUDED)
    headers_list = list(map(os.path.basename, mh))
    # sort alphabetical order
    headers_list.sort()
    return headers_list


def test_get_all_module_headers():
    # 'Standard' should return some files (at lease 10)
    # this number depends on the OCE version
    headers_list_1 = get_all_module_headers("Standard")
    assert len(list(headers_list_1)) > 10
    # an empty list
    headers_list_2 = list(get_all_module_headers("something_else"))
    assert not headers_list_2


def check_has_related_handle(class_name):
    """ For a given class :
    Check if a header exists.
    """
    if check_is_persistent(class_name):
        return False

    filename = os.path.join(OCE_INCLUDE_DIR, "Handle_%s.hxx" % class_name)
    other_possible_filename = filename
    if class_name.startswith("Graphic3d"):
        other_possible_filename = os.path.join(OCE_INCLUDE_DIR, "%s_Handle.hxx" % class_name)
    return os.path.exists(filename) or os.path.exists(other_possible_filename) or need_handle(class_name)


def need_handle(class_name):
    """ Returns True if the current parsed class needs an
    Handle to be defined. This is useful when headers define
    handles but no header """
    # @TODO what about DEFINE_RTTI ?
    return class_name in ALL_STANDARD_HANDLES or class_name in ALL_STANDARD_TRANSIENTS


def adapt_header_file(header_content):
    """ take an header filename as input.
    Returns the output of a tempfile with :
    * all occurrences of Handle(something) moved to Handle_Something
    otherwise CppHeaderParser is confused ;
    * all define RTTI moved
    """
    global ALL_STANDARD_HANDLES, ALL_HARRAY1, ALL_HARRAY2, ALL_HSEQUENCE
    # search for STANDARD_HANDLE
    outer = re.compile("DEFINE_STANDARD_HANDLE[\\s]*\\([\\w\\s]+\\,+[\\w\\s]+\\)")
    matches = outer.findall(header_content)
    if matches:
        for match in matches:
            # @TODO find inheritance name
            header_content = header_content.replace('DEFINE_STANDARD_HANDLE',
                                                    '//DEFINE_STANDARD_HANDLE')
            ALL_STANDARD_HANDLES.append(match.split('(')[1].split(',')[0])
    # Search for RTTIEXT
    outer = re.compile("DEFINE_STANDARD_RTTIEXT[\\s]*\\([\\w\\s]+\\,+[\\w\\s]+\\)")
    matches = outer.findall(header_content)
    if matches:
        for match in matches:
            # @TODO find inheritance name
            header_content = header_content.replace('DEFINE_STANDARD_RTTIEXT',
                                                    '//DEFINE_STANDARD_RTTIEXT')
    # Search for HARRAY1
    outer = re.compile("DEFINE_HARRAY1[\\s]*\\([\\w\\s]+\\,+[\\w\\s]+\\)")
    matches = outer.findall(header_content)
    if matches:
        for match in matches:
            # @TODO find inheritance name
            typename = match.split('(')[1].split(',')[0]
            base_typename = match.split(',')[1].split(')')[0]
            # we keep only te RTTI that are defined in this module,
            # to avoid cyclic references in the SWIG files
            logging.info("Found HARRAY1 definition" + typename + ':' + base_typename)
            ALL_HARRAY1[typename] = base_typename.strip()
    # Search for HARRAY2
    outer = re.compile("DEFINE_HARRAY2[\\s]*\\([\\w\\s]+\\,+[\\w\\s]+\\)")
    matches = outer.findall(header_content)
    if matches:
        for match in matches:
            # @TODO find inheritance name
            typename = match.split('(')[1].split(',')[0]
            base_typename = match.split(',')[1].split(')')[0]
            # we keep only te RTTI that are defined in this module,
            # to avoid cyclic references in the SWIG files
            logging.info("Found HARRAY2 definition" + typename + ':' + base_typename)
            ALL_HARRAY2[typename] = base_typename.strip()
   # Search for HSEQUENCE
    outer = re.compile("DEFINE_HSEQUENCE[\\s]*\\([\\w\\s]+\\,+[\\w\\s]+\\)")
    matches = outer.findall(header_content)
    if matches:
        for match in matches:
            # @TODO find inheritance name
            typename = match.split('(')[1].split(',')[0]
            base_typename = match.split(',')[1].split(')')[0]
            # we keep only te RTTI that are defined in this module,
            # to avoid cyclic references in the SWIG files
            logging.info("Found HSEQUENCE definition" + typename + ':' + base_typename)
            ALL_HSEQUENCE[typename] = base_typename.strip()
    # skip some defines that prevent header parsing
    header_content = header_content.replace('DEFINE_STANDARD_RTTI_INLINE',
                                            '//DEFINE_STANDARD_RTTI_INLINE')
    header_content = header_content.replace('Standard_DEPRECATED',
                                            '//Standard_DEPRECATED')
    header_content = header_content.replace('DECLARE_TOBJOCAF_PERSISTENCE',
                                            '//DECLARE_TOBJOCAF_PERSISTENCE')
    # remove stuff that prevent CppHeaderPArser to work correctly    
    header_content = header_content.replace('DEFINE_STANDARD_ALLOC', '')
    header_content = header_content.replace('Standard_EXPORT', '')
    header_content = header_content.replace('Standard_NODISCARD', '')
    # TODO : use the @deprecated python decorator to raise a Deprecation exception
    # see https://github.com/tantale/deprecated
    # each time this method is used
    # then we look for Handle(Something) use
    # and replace with opencascade::handle<Something>
    outer = re.compile("Handle[\\s]*\\([\\w\\s]*\\)")
    matches = outer.findall(header_content)
    if matches:
        for match in matches:
            # matches are of the form :
            #['Handle(Graphic3d_Structure)',
            # 'Handle(Graphic3d_DataStructureManager)']
            match = match.replace(" ", "")
            class_name = (match.split('Handle(')[1]).split(')')[0]
            if class_name == "" or not class_name[0].isupper():
                continue
            header_content = header_content.replace(match,
                                                    'opencascade::handle<%s>' % class_name)
    return header_content


def parse_header(header_filename):
    """ Use CppHeaderParser module to parse header_filename
    """
    header_content = open(header_filename, 'r', encoding='ISO-8859-1').read()
    adapted_header_content = adapt_header_file(header_content)
    try:
        cpp_header = CppHeaderParser.CppHeader(adapted_header_content, "string")
    except CppHeaderParser.CppParseError as e:
        print(e)
        print("Filename : %s" % header_filename)
        print("FileContent :\n", adapted_header_content)
        sys.exit(1)
    return cpp_header


def filter_typedefs(typedef_dict):
    """ Remove some strange thing that generated SWIG
    errors
    """
    if '{' in typedef_dict:
        del typedef_dict['{']
    if ':' in typedef_dict:
        del typedef_dict[':']
    for key in list(typedef_dict):
        if key in TYPEDEF_TO_EXCLUDE:
            del typedef_dict[key]
    for key in list(typedef_dict):
        typedef_dict[key] = typedef_dict[key].replace(" ::", "::")
        typedef_dict[key] = typedef_dict[key].replace(" , ", ", ")
    return typedef_dict


def test_filter_typedefs():
    a_dict = {'1': 'one', '{': 'two', 'NCollection_DelMapNode':'3'}
    assert filter_typedefs(a_dict) == {'1': 'one'}


def get_type_for_ncollection_array(ncollection_array: str) -> str:
    """ input : NCollection_Array1<Standard_Real>
    output : Standard_Real
    """
    return ncollection_array.split('<')[1].split('>')[0].strip()


def test_get_type_for_ncollection_array() -> None:
    assert get_type_for_ncollection_array("NCollection_Array1<Standard_Real>") == "Standard_Real"


def process_templates_from_typedefs(list_of_typedefs):
    """
    """
    wrapper_str = "/* templates */\n"
    pyi_str = ""
    for t in list_of_typedefs:
        template_name = t[1].replace(" ", "")
        template_type = t[0]
        if "unsigned" not in template_type and "const" not in template_type:
          template_type = template_type.replace(" ", "")
        # we must include
        if not (template_type.endswith("::Iterator") or template_type.endswith("::Type")):  #it's not an iterator
            # check that there's no forbidden template
            wrap_template = True
            for forbidden_template in TEMPLATES_TO_EXCLUDE:
                if forbidden_template in template_type:
                    wrap_template = False
            # sometimes the template name is weird (parenthesis, commma etc.)
            # don't consider this
            if not "_" in template_name:
                wrap_template = False
                logging.warning("Template: " + template_name + "skipped because name does'nt contain _.")
            if wrap_template:
                wrapper_str += "%%template(%s) %s;\n" %(template_name, template_type)
                # if a NCollection_Array1, extend this template to benefit from pythonic methods
                # All "Array1" classes are considered as python arrays
                # TODO : it should be a good thing to use decorators here, to avoid code duplication
                basetype_hint = adapt_type_for_hint(get_type_for_ncollection_array(template_type))
                if 'NCollection_Array1' in template_type:
                    wrapper_str += NCOLLECTION_ARRAY1_EXTEND_TEMPLATE.replace("NCollection_Array1_Template_Instanciation", template_type)
                    str1 = NCOLLECTION_ARRAY1_EXTEND_TEMPLATE_PYI.replace("NCollection_Array1_Template_Instanciation", template_name)
                    pyi_str += str1.replace("Type_T", "%s" % basetype_hint)
                elif 'NCollection_List' in template_type:
                    wrapper_str += NCOLLECTION_LIST_EXTEND_TEMPLATE.replace("NCollection_List_Template_Instanciation", template_type)
                    str1 = NCOLLECTION_LIST_EXTEND_TEMPLATE_PYI.replace("NCollection_List_Template_Instanciation", template_name)
                    pyi_str += str1.replace("Type_T", "%s" % basetype_hint)
                elif 'NCollection_Sequence' in template_type:
                    wrapper_str += NCOLLECTION_SEQUENCE_EXTEND_TEMPLATE.replace("NCollection_Sequence_Template_Instanciation", template_type)
                    str1 = NCOLLECTION_SEQUENCE_EXTEND_TEMPLATE_PYI.replace("NCollection_Sequence_Template_Instanciation", template_name)
                    pyi_str += str1.replace("Type_T", "%s" % basetype_hint)
                
                elif 'NCollection_DataMap' in template_type:
                    # NCollection_Datamap is similar to a Python dict,
                    # it's a (key, value) store. Defined as
                    # template < class TheKeyType,
                    # class TheItemType,
                    #class Hasher = NCollection_DefaultHasher<TheKeyType> >
                    # some occt method return such an object, but the iterator can't be accessed
                    # through Python. Se we extend this class with a Keys() methd that iterates over
                    # NCollection_DataMap keys and returns a Python list of key objects.
                    # Note : works for standard_Integer keys only so far
                    if '<Standard_Integer' in template_type:
                        ncollection_datamap_extent = NCOLLECTION_DATAMAP_EXTEND_TEMPLATE.replace("NCollection_DataMap_Template_Instanciation", template_type)
                        ncollection_datamap_extent = ncollection_datamap_extent.replace("NCollection_DataMap_Template_Name", template_name)
                        wrapper_str += ncollection_datamap_extent
        elif template_name.endswith("Iter") or "_ListIteratorOf" in template_name:  # it's a lst iterator, we use another way to wrap the template
        # #%template(TopTools_ListIteratorOfListOfShape) NCollection_TListIterator<TopTools_ListOfShape>;
            if "IteratorOf" in template_name:
                if not "::handle" in template_type:
                    typ = (template_type.split('<')[1]).split('>')[0]
                else:
                    h_typ = (template_type.split('<')[2]).split('>')[0]
                    typ = "opencascade::handle<%s>" % h_typ
            elif template_name.endswith("Iter"):
                typ = template_name.split('Iter')[0]
            wrapper_str += "%%template(%s) NCollection_TListIterator<%s>;\n" %(template_name, typ)
    wrapper_str += "/* end templates declaration */\n"
    return wrapper_str, pyi_str

def adapt_type_for_hint_typedef(typedef_type_str):
    typedef_type_str = typedef_type_str.replace(' *', '')
    typedef_type_str = typedef_type_str.replace('&OutValue', '')
    if 'char' in typedef_type_str or 'Char' in typedef_type_str:
        typedef_type_str = "str"
    if '_int' in typedef_type_str or " int" in typedef_type_str or " long" in typedef_type_str:
        typedef_type_str = "int"
    if 'double' in typedef_type_str:
        typedef_type_str = "float"
    if 'void' in typedef_type_str or "VOID" in typedef_type_str:
        typedef_type_str = "None"
    if 'GUID' in typedef_type_str:
        typedef_type_str = "str"
    if 'size_t' in typedef_type_str:
        typedef_type_str = "int"
    if 'struct' in typedef_type_str:
        typedef_type_str = "int"
    return typedef_type_str

def process_typedefs(typedefs_dict):
    """ Take a typedef dictionary and returns a SWIG definition string
    """
    templates_str = ""
    typedef_pyi_str = ""  # NewTypes related to typedef aliases
    typedef_str = "/* typedefs */\n"
    templates = []
    # careful, there might be some strange things returned by CppHeaderParser
    # they should not be taken into account
    filtered_typedef_dict = filter_typedefs(typedefs_dict)
    # we check if there is any type def type that relies on an opencascade::handle
    # if this is the case, we must add the corresponding python module
    # as a dependency otherwise it leads to a runtime issue

    for template_type in filtered_typedef_dict.values():
        if "opencascade::handle" in template_type: # we must add a PYTHON DEPENDENCY
            if template_type.count('<') == 2:
                h_typ = (template_type.split('<')[2]).split('>')[0]
            elif template_type.count('<') == 1:
                h_typ = (template_type.split('<')[1]).split('>')[0]
            else:
                logging.warning("This template type cannot be handled: " + template_type)
                continue
            module = h_typ.split("_")[0]
            if module != CURRENT_MODULE:
                # need to be added to the list of dependend object
                if (module not in PYTHON_MODULE_DEPENDENCY) and (is_module(module)):
                    PYTHON_MODULE_DEPENDENCY.append(module)

    sorted_list_of_typedefs = list(filtered_typedef_dict.keys())
    sorted_list_of_typedefs.sort()

    for typedef_value in sorted_list_of_typedefs:
        # some occttype defs are actually templated classes,
        # for instance
        # typedef NCollection_Array1<Standard_Real> TColStd_Array1OfReal;
        # this must be wrapped as a typedef but rather as an instaicated class
        # the good way to proceed is:
        # %{include "NCollection_Array1.hxx"}
        # %template(TColStd_Array1OfReal) NCollection_Array1<Standard_Real>;
        # we then check if > or < are in the typedef string then we process it.
        if ("<" in "%s" % filtered_typedef_dict[typedef_value] or
                ">" in "%s" % filtered_typedef_dict[typedef_value]):
            templates.append([filtered_typedef_dict[typedef_value], typedef_value])
        typedef_str += "typedef %s %s;\n" % (filtered_typedef_dict[typedef_value], typedef_value)
        check_dependency(filtered_typedef_dict[typedef_value].split()[0])
        # Define a new type, only for aliases
        type_to_define = filtered_typedef_dict[typedef_value]
        if ('<' not in type_to_define and
            ':' not in type_to_define and
            'struct' not in type_to_define and
            ')' not in type_to_define and
            'NCollection_Array1' not in type_to_define and  # because it has a special hint
            'NCollection_List' not in type_to_define and  # because it has a special hint
            'NCollection_DataMap' not in type_to_define and  # because it has a special hint
            'NCollection_Sequence' not in type_to_define and  # because it has a special hint
            type_to_define is not None):
            type_to_define = adapt_type_for_hint_typedef(type_to_define)
            typedef_pyi_str += "\n%s = NewType('%s', %s)" % (typedef_value, typedef_value, type_to_define)
        elif (')' not in typedef_value and
              '(' not in typedef_value and
              ':' not in typedef_value and
              'NCollection_Array1' not in type_to_define and
              'NCollection_List' not in type_to_define and
              'NCollection_DataMap' not in type_to_define and
              'NCollection_Sequence' not in type_to_define):
            typedef_pyi_str += "\n#the following typedef cannot be wrapped as is"
            typedef_pyi_str += "\n%s = NewType('%s', Any)" % (typedef_value, typedef_value)

    typedef_pyi_str += "\n"
    typedef_str += "/* end typedefs declaration */\n\n"
    # then we process templates
    # at this stage, we get a list as follows
    templates_def, templates_pyi = process_templates_from_typedefs(templates)
    templates_str += templates_def
    templates_str += "\n"
    return templates_str + typedef_str, typedef_pyi_str + templates_pyi


def process_enums(enums_list):
    """ Take an enum list and generate a compliant SWIG string
    Then create a python class that mimics the enum
    for instance, from the TopAbs_Orientation.hxx header, we have
    enum TopAbs_Orientation
    {
    TopAbs_FORWARD,
    TopAbs_REVERSED,
    TopAbs_INTERNAL,
    TopAbs_EXTERNAL
    };

    In SWIG, this will be wrapped in the interface file as
    
    enum TopAbs_Orientation {
      TopAbs_FORWARD = 0,
      TopAbs_REVERSED = 1,
      TopAbs_INTERNAL = 2,
      TopAbs_EXTERNAL = 3,
    };

    However, python does not know anything about TopAbs_Orientation, he only knows TopAbs_FORWARD
    So we also create a python class that mimics the enum and let python know about the TopAbs_Orientation type

    %pythoncode {
    class TopAbs_Orientation:
        TopAbs_FORWARD = 0
        TopAbs_REVERSED = 1
        TopAbs_INTERNAL = 2
        TopAbs_EXTERNAL = 3
    }

    Then, from python, it's possible to use:
    >>> TopAbs_Orientation.TopAbs_FORWARD

    Note: this only makes sense for named enums
    """
    enum_str = "/* public enums */\n"

    enum_python_proxies = "/* python proy classes for enums */\n"
    enum_python_proxies += "%pythoncode {\n"

    enum_pyi_str = ""
    # loop over enums
    for enum in enums_list:
        alias_str = ""
        python_proxy = True
        if "name" not in enum:
            enum_name = ""
            python_proxy = False
        else:
            enum_name = enum["name"]
            if not enum_name in ALL_ENUMS:
                ALL_ENUMS.append(enum_name)
        enum_str += "enum %s {\n" % enum_name
        if python_proxy:
            enum_python_proxies += "\nclass %s(IntEnum):\n" % enum_name
            enum_pyi_str += "\nclass %s(IntEnum):\n" % enum_name
        for enum_value in enum["values"]:
            enum_str += "\t%s = %s,\n" % (enum_value["name"], enum_value["value"])
            if python_proxy:
                enum_python_proxies += "\t%s = %s\n" % (enum_value["name"], enum_value["value"])
                enum_pyi_str += "\t%s: int = ...\n" % enum_value["name"]
                # then, in both proxy and stub files, we create the alias for each named enum,
                # for instance
                # gp_IntrisicXYZ = gp_EulerSequence.gp_IntrinsicXYZ
                alias_str += "%s = %s.%s\n" % (enum_value["name"], enum_name, enum_value["name"])
        enum_python_proxies += alias_str
        enum_pyi_str += alias_str
        enum_str += "};\n\n"
        
    enum_python_proxies += "};\n"
    enum_str += "/* end public enums declaration */\n\n"
    enum_python_proxies += "/* end python proxy for enums */\n\n"
    return enum_str + enum_python_proxies, enum_pyi_str


def is_return_type_enum(return_type):
    """ This method returns True is an enum is returned. For instance:
    BRepCheck_Status &
    BRepCheck_Status
    """
    for r in return_type.split():
        if r in ALL_ENUMS:
            return True
    return False


def adapt_param_type(param_type):
    param_type = param_type.strip()
    param_type = param_type.replace("Standard_CString", "const char *")
    param_type = param_type.replace("DrawType", "NIS_Drawer::DrawType")
    # some enums are type defs and not properly handled by swig
    # these are Standard_Integer
    for pattern in STANDARD_INTEGER_TYPEDEF:
        if pattern in param_type:
            if "const" in param_type and "&" in param_type:
                # const pattern is wrapped as an integer
                param_type = param_type.replace(pattern, "int")
                param_type = param_type.replace("const", "")
                param_type = param_type.replace("&", "")
            elif "const" in param_type:
                param_type = param_type.replace("const", "")
                param_type = param_type.replace(pattern, "int")
            elif "&" in param_type: # pattern & is an out value
                param_type = param_type.replace("&", "")
                param_type = param_type.replace(pattern, "Standard_Integer &OutValue")
            elif pattern == param_type:
                param_type = param_type.replace(pattern, "int")
            else:
                logging.warning("Unknown pattern in Standard_Integer typedef")
    param_type = param_type.strip()
    check_dependency(param_type)
    return param_type


def adapt_param_type_and_name(param_type_and_name):
    """ We sometime need to replace some argument type and name
    to properly deal with byref values
    """
    if (('Standard_Real &' in param_type_and_name) or
            ('Quantity_Parameter &' in param_type_and_name) or
            ('Quantity_Length &' in param_type_and_name) or
            ('V3d_Coordinate &' in param_type_and_name) or
            (param_type_and_name.startswith('double &'))) and not 'const' in param_type_and_name:
        adapted_param_type_and_name = "Standard_Real &OutValue"
    elif (('Standard_Integer &' in param_type_and_name) or
          (param_type_and_name.startswith('int &'))) and not 'const' in param_type_and_name:
        adapted_param_type_and_name = "Standard_Integer &OutValue"
    elif (('Standard_Boolean &' in param_type_and_name) or
          (param_type_and_name.startswith('bool &'))) and not 'const' in param_type_and_name:
        adapted_param_type_and_name = "Standard_Boolean &OutValue"
    elif 'FairCurve_AnalysisCode &' in param_type_and_name:
        adapted_param_type_and_name = 'FairCurve_AnalysisCode &OutValue'
    else:
        adapted_param_type_and_name = param_type_and_name
    if "& &" in adapted_param_type_and_name:
        adapted_param_type_and_name = adapted_param_type_and_name.replace("& &", "&")
    return adapted_param_type_and_name


def test_adapt_param_type_and_name():
    p1 = "Standard_Real & Xp"
    ad_p1 = adapt_param_type_and_name(p1)
    assert ad_p1 == "Standard_Real &OutValue"
    p2 = "Standard_Integer & I"
    ad_p2 = adapt_param_type_and_name(p2)
    assert ad_p2 == "Standard_Integer &OutValue"
    p3 = "int & j"
    ad_p3 = adapt_param_type_and_name(p3)
    assert ad_p3 == "Standard_Integer &OutValue"
    p4 = "double & x"
    ad_p4 = adapt_param_type_and_name(p4)
    assert ad_p4 == "Standard_Real &OutValue"


def check_dependency(item):
    """ For any type or class name passe to this function,
    returns the module name to which it belongs.
    a. Handle_Geom_Curve -> Geom
    b. Handle ( Geom2d_Curve) -> Geom2d
    c. opencascade::handle<TopoDS_TShape> -> TopoDS
    d. TopoDS_Shape -> TopoDS
    For the case 1 (a, b, c), the module has to be added to the headers list
    For the case 2 (d), the module TopoDS.i has to be added as a dependency in
    order that the class hierarchy is propagated.
    """
    if not item:
        return False
    filt = ["const ", "static ", "virtual ", "clocale_t", "pointer",
            "size_type", "void", "reference", "const_", "inline "]
    for f in filt:
        item = item.replace(f, '')
    if not item:  # if item list is empty
        return False
    # the element can be either a template ie Handle(Something) else Something_
    # or opencascade::handle<Some_Class>
    if item.startswith("Handle ("):
        item = item.split("Handle ( ")[1].split(")")[0].strip()
        module = item.split('_')[0]
    elif item.startswith("Handle_"):
        module = item.split('_')[1]
    elif item.startswith("opencascade::handle<"):
        item = item.split("<")[1].split(">")[0].strip()
        module = item.split('_')[0]
    elif item.count('_') > 0:  # Standard_Integer or NCollection_CellFilter_InspectorXYZ
        module = item.split('_')[0]
    else:  # do nothing, it's a trap
        return False
    # we strip the module, who knows, there maybe trailing spaces
    module = module.strip()
    # TODO : is the following line really necessary ?
    if module == 'Font':  # forget about Font dependencies, issues with FreeType
        return True
    if module != CURRENT_MODULE:
        # need to be added to the list of dependend object
        if (module not in PYTHON_MODULE_DEPENDENCY) and (is_module(module)):
            PYTHON_MODULE_DEPENDENCY.append(module)
    return module


def test_check_dependency():
    dep1 = check_dependency("Handle_Geom_Curve")
    assert dep1 == "Geom"
    dep2 = check_dependency("Handle ( Geom2d_Curve)")
    assert dep2 == "Geom2d"
    dep3 = check_dependency("opencascade::handle<TopoDS_TShape>")
    assert dep3 == "TopoDS"
    dep4 = check_dependency("Standard_Integer")
    assert dep4 == "Standard"


def adapt_return_type(return_type):
    """ adapt the type definition
    """
    replaces = ["public", "protected : private",  # TODO: CppHeaderParser may badly parse these methods
                "DEFINE_NCOLLECTION_ALLOC :",
                "DEFINE_NCOLLECTION_ALLOC"]
    for replace in replaces:
        return_type = return_type.replace(replace, "")
    return_type = return_type.strip()
    # replace Standard_CString with char *
    return_type = return_type.replace("Standard_CString", "const char *")
    # remove const if const virtual double *
    return_type = return_type.replace(": static", "static")
    return_type = return_type.replace(": const", "const")
    return_type = return_type.replace("const virtual double *", "virtual double *")
    return_type = return_type.replace("TAncestorMap", "TopTools_IndexedDataMapOfShapeListOfShape")
    # for instance "const TopoDS_Shape & -> ["const", "TopoDS_Shape", "&"]
    # opencascade::handle may contain extra spaces, that has to be removed
    if "opencascade::handle" in return_type:
        return_type = return_type.replace(" >", ">")
    if (('gp' in return_type) and not 'TColgp' in return_type) or ('TopoDS' in return_type):
        return_type = return_type.replace('&', '').strip()
    check_dependency(return_type)
    # check is it is an enum
    if is_return_type_enum(return_type) and "&" in return_type:
        # remove the reference
        return_type = return_type.replace("&", "")
    return return_type


def test_adapt_return_type():
    adapted_1 = adapt_return_type("Standard_CString")
    assert adapted_1 == "const char *"
    adapted_2 = adapt_return_type("gp_Dir &")
    assert adapted_2 == "gp_Dir"


def adapt_function_name(f_name):
    """ Some function names may result in errors with SWIG
    """
    f_name = f_name.replace("operator", "operator ")
    return f_name


def test_adapt_function_name():
    assert adapt_function_name('operator*') == 'operator *'


def get_module_docstring(module_name):
    """ The module docstring is not provided anymore in cdl files since
    opencascade 7 and higher was released.
    Instead, the link to the official package documentation is
    used, for instance, for the gp package:
    https://www.opencascade.com/doc/occt-7.4.0/refman/html/package_gp.html
    """
    module_docstring = "%s module, see official documentation at\n" % module_name
    module_docstring += "https://www.opencascade.com/doc/occt-7.4.0/refman/html/package_%s.html" % module_name.lower()
    return module_docstring


def process_function_docstring(f):
    """ Create the docstring, for the function f,
    that will be used by the wrapper.
    For that, first check the function parameters and type
    then add the doxygen value.
    We use the numpy doc docstring convention see
    https://numpydoc.readthedocs.io/en/latest/format.html
    """
    function_name = f["name"]
    function_name = adapt_function_name(function_name)
    string_to_return = '\t\t%feature("autodoc", "'
    # the returns
    ret = []
    # first process parameters
    parameters_string = ''
    if f["parameters"]:  # at leats one element in the least
        # we add a "Parameters section"
        parameters_string += "\nParameters\n----------\n"
        for param in f["parameters"]:
            param_type = adapt_param_type(param["type"])
            # remove const and &
            param_type = fix_type(param_type)
            # we change opencascade::handle<XXX> & to XXX
            if 'opencascade::handle' in param_type:
                param_type = param_type.split('opencascade::handle<')[1].split('>')[0]
            # in the docstring, we don't care about the "&"
            # it's not the matter of a python user
            param_type = param_type.replace("&", "")
            # same for the const
            param_type = param_type.replace("const", "")
            param_type = param_type.strip()
            # check the &OutValue
            the_type_and_name = param["type"] + param["name"]
            popo = adapt_param_type_and_name(the_type_and_name)
            if 'OutValue' in popo:
                # this parameter has to be added to the
                # returns, not the parameters of the python method
                ret.append("%s: %s" % (param["name"], param_type))
                continue
            # add the parameter to the list
            parameters_string += "%s: %s" % (param["name"], param_type)
            if "defaultValue" in param:
                parameters_string += ",optional\n"
                def_value = adapt_default_value(param["defaultValue"])
                parameters_string += "\tdefault value is %s" % def_value           
            parameters_string += "\n"
    # return types:
    returns_string = 'Returns\n-------\n'
    method_return_type = adapt_return_type(f["rtnType"])
    if len(ret) >= 1: # at least on by ref parameter
        for r in ret:
            returns_string += "%s\n" % r
    elif method_return_type != 'void':
        method_return_type = method_return_type.replace("&", "")
        #ret = ret.replace("virtual", "")
        method_return_type = fix_type(method_return_type)
        method_return_type = method_return_type.replace(": static ", "")
        method_return_type = method_return_type.replace("static ", "")
        method_return_type = method_return_type.strip()
        returns_string += "%s\n" % method_return_type
    else:
        returns_string += "None\n"
    # process doxygen strings
    doxygen_string = "No available documentation.\n"
    if "doxygen" in f:
        doxygen_string = f["doxygen"]
        # remove comment separator
        doxygen_string = doxygen_string.replace("//! ", "")
        # replace " with '
        doxygen_string = doxygen_string.replace('"', "'")
        # remove ??/ that causes a compilation issue in InterfaceGraphic
        doxygen_string = doxygen_string.replace("??", "")
        # remove <br>
        # first, a strange thing in BSplClib
        doxygen_string = doxygen_string.replace('\\ <br>', " ")
        doxygen_string = doxygen_string.replace('<br>', "")
        # replace <me> with <self>, which is more pythonic
        doxygen_string = doxygen_string.replace('<me>', "<self>")
        # make '\r' correctly processed
        doxygen_string = doxygen_string.replace(r"\\return", "Returns")
        doxygen_string = doxygen_string.replace("\\r", "")
        # replace \n with space
        doxygen_string = doxygen_string.replace("\n", " ")
        doxygen_string = doxygen_string.replace("'\\n'", "A newline")
        # replace TRUE and FALSE with True and False
        doxygen_string = doxygen_string.replace("TRUE", "True")
        doxygen_string = doxygen_string.replace("FALSE", "False")
        # misc
        doxygen_string = doxygen_string.replace("@return", "returns")
        # replace the extra spaces
        doxygen_string = doxygen_string.replace('    ', " ")
        doxygen_string = doxygen_string.replace('   ', " ")
        doxygen_string = doxygen_string.replace('  ', " ")

        doxygen_string = doxygen_string.capitalize()
        if not doxygen_string.endswith("."):
            doxygen_string = doxygen_string + "."
        # then remove spaces from start and end
        doxygen_string = doxygen_string.strip() + "\n"
    # concatenate everything
    final_string = doxygen_string + parameters_string + '\n' + returns_string
    string_to_return += '%s") %s;\n' % (final_string, function_name)
    return string_to_return


def adapt_default_value(def_value):
    """ adapt default value """
    def_value = def_value.replace(' ', '')
    def_value = def_value.replace('"', "'")
    def_value = def_value.replace("''", '""')
    return def_value


def adapt_default_value_parmlist(parm):
    """ adapts default value to be used in swig parameter list """
    def_value = parm["defaultValue"]
    def_value = def_value.replace(' ', '')
    return def_value


def test_adapt_default_value():
    pass#assert adapt_default_value(": : MeshDim_3D") == "MeshDim_3D"


def filter_member_functions(class_name, class_public_methods, member_functions_to_exclude, class_is_abstract):
    """ This functions removes member function to exclude from
    the class methods list. Some of the members functions have to be removed
    because they can't be wrapped (usually, this results in a linkage error)
    """
    # split wrapped methods into twoo lists
    constructors = []
    other_methods = []
    member_functions_to_process = []
    for public_method in class_public_methods:
        method_name = public_method["name"]
        if method_name in member_functions_to_exclude:
            continue
        if class_is_abstract and public_method["constructor"]:
            logging.warning("Constructor skipped for abstract class %s" % class_name)
            continue
        if method_name == "ShallowCopy":  # specific to 0.17.1 and Mingw
            continue
        if "<" in method_name:
            continue
        # finally, we add this method to process in the correct list
        if public_method["constructor"]:
            constructors.append(public_method)
        else:
            other_methods.append(public_method)
    return constructors, other_methods


def adapt_type_for_hint(type_str):
    """ convert c++ types to python types, for type hints
    Returns False if there's no possible type
    """
    if type_str == "0":  # huu ? in XCAFDoc, skip it
        logging.warning("\t[TypeHint] Skipping unknown type, 0")
        return False
    if "void" in type_str or type_str in [""]:
        return "None"
    if " int"in type_str:  # const int, unsigned int etc.
        return "int"
    if "char *" in type_str:
        return "str"
    if not "_" in type_str:  # TODO these are special cases, e.g. nested classes
        logging.warning("\t[TypeHint] Skipping type %s, should contain _" % type_str)
        return False  # returns a boolean to prevent type hint creation, the type will not be found
    # we only keep what is
    for tp in type_str.split(" "):
        if "_" in tp:
            type_str = tp.strip()
            break

    type_str = type_str.replace("Standard_Integer", "int")
    type_str = type_str.replace("Standard_Real", "float")
    type_str = type_str.replace("Standard_ShortReal", "float")
    type_str = type_str.replace("Standard_Boolean", "bool")
    type_str = type_str.replace("Standard_Character", "str")
    type_str = type_str.replace("Standard_Byte", "str")
    type_str = type_str.replace("Standard_Address", "None")
    type_str = type_str.replace("Standard_Size", "int")
    type_str = type_str.replace("Standard_Time", "float")

    # transform opencascade::handle<Message_Alert> to return Message_Alert
    if type_str.startswith("opencascade::handle<"):
        type_str = type_str[20:].split(">")[0].strip()
    if ":" in type_str:
        logging.warning("\t[TypeHint] Skip type %s, because of trailing :" % type_str)
        return False
    if "_" in type_str and not is_module(type_str.split('_')[0]):
        logging.warning("\t[TypeHint] Skipping unknown type, %s not in module list" % type_str.split('_')[0])
        return False
    if type_str.count('<') >= 1:  # at least one <, it's a template
        logging.warning("\t[TypeHint] Skipping type %s, seems to be a template" % type_str) 
        return False
    return type_str


def get_classname_from_handle(handle_name):
    """ input : opencascade::handle<Something>
    returns: Something
    """
    if handle_name.startswith("opencascade::handle<"):
        class_name = handle_name[20:].split(">")[0].strip()

    return class_name


def adapt_type_hint_parameter_name(param_name_str):
    """ some parameter names may conflict with python keyword,
    for instance with, False etc.
    Returns the modified name, and wether to take it into accound"""
    if keyword.iskeyword(param_name_str):
        new_param_name = param_name_str + "_"
        success = True
    elif param_name_str == "":
        new_param_name = "x"  # give a fake name
        success = True
    elif param_name_str == '&':
        new_param_name = ""
        success = False
    else:  # default
        new_param_name = param_name_str
        success = True
    if '[' in new_param_name:
        # something like 
        param_name, snd_part = new_param_name.split('[')
        param_name = param_name.replace(')', '')
        number = snd_part.split(']')[0]
        if param_name == "":
            success = False
        else:
            new_param_name = param_name + "_list"
            success = True
    return new_param_name, success


def adapt_type_hint_default_value(default_value_str):
    """ default values such as Standard_True etc. must be
    converted to correct python values
    """
    if default_value_str == "Standard_True":
        new_default_value_str = "True"
        success = True
    elif default_value_str == "Standard_False":
        new_default_value_str = "False"
        success = True
    elif "Precision::" in default_value_str:
        new_default_value_str = default_value_str.replace("Precision::", "precision_")
        success = True
    elif default_value_str == "NULL":
        new_default_value_str = "None"
        success = True
    elif "opencascade::handle" in default_value_str:
        # case opencascade::handle<Message_ProgressIndicator>()
        # should be Message_ProgressIndicator()
        classname = get_classname_from_handle(default_value_str)
        if classname == "Message_ProgressIndicator":  # no constructor defined, abstract class
            new_default_value_str = "'Message_ProgressIndicator()'"
        else:
          new_default_value_str = classname + default_value_str.split('>')[1]
        success = True
    elif default_value_str.endswith('f'):  # some float values are defined as 0.0f or 0.1f
        str_removed_final_f = default_value_str[:-1]
        try:
            float(str_removed_final_f)
            is_float = True
        except ValueError:
            is_float = False
        if is_float:
            new_default_value_str = str_removed_final_f 
            success = True
        else:
            new_default_value_str = default_value_str
            success = True
    else:
        new_default_value_str = default_value_str
        success = True
    return new_default_value_str, success


def process_function(f, overload=False):
    """ Process function f and returns a SWIG compliant string.
    If process_docstrings is set to True, the documentation string
    from the C++ header will be used as is for the python wrapper
    f : a dict for the function f
    overload: False by default, True if other method with the same name exists
    """
    global NB_TOTAL_METHODS, CURRENT_MODULE_PYI_STATIC_METHODS_ALIASES
    if f["template"]:
        return False, ""
    # first, adapt function name, if needed
    function_name = adapt_function_name(f["name"])
    ################################################
    # Cases where the method should not be wrapped #
    ################################################
    # destructors are not wrapped
    if f["destructor"]:
        return "", ""
    if f["returns"] == "~":
        return "", ""  # a destructor that should be considered as a destructor
    if "TYPENAME" in f["rtnType"]:  # TODO remove
        return "", ""  # something in NCollection
    if function_name == "DEFINE_STANDARD_RTTIEXT":  # TODO remove
        return "", ""
    if function_name == "Handle":  # TODO: make it possible!
    # this is because Handle (something) some function can not be
    # handled by swig
        return "", ""
    #############
    # Operators #
    #############
    operator_wrapper = {"+": None,  # wrapped by SWIG, no need for a custom template
                        "-": None,  # wrapped by SWIG, no need for a custom template
                        "*": None,  # wrapped by SWIG, no need for a custom template
                        "/": None,  # wrapped by SWIG, no need for a custom template
                        "==": TEMPLATE__EQ__,
                        "!=": TEMPLATE__NE__,
                        "+=": TEMPLATE__IADD__,
                        "*=": TEMPLATE__IMUL__,
                        "-=": TEMPLATE__ISUB__,
                        "/=": TEMPLATE__ITRUEDIV__}
    if "operator" in function_name:
        operand = function_name.split("operator ")[1].strip()
        # if not allowed, just skip it
        if not operand in operator_wrapper:
            return "", ""
        ##############################################
        # Cases where the method is actually wrapped #
        ##############################################
        if operator_wrapper[operand] is not None:
            param = f["parameters"][0]
            param_type = param["type"].replace("&", "").strip()
            return operator_wrapper[operand] % param_type, ""  # not hint for operator

    # at this point, we can increment the method counter
    NB_TOTAL_METHODS += 1
    
    # special case : Standard_OStream or Standard_IStream is the only parameter
    if len(f["parameters"]) == 1:
        param = f["parameters"][0]
        param_type = param["type"].replace("&", "").strip()
        if 'Standard_OStream' in '%s' % param_type:
            str_function = TEMPLATE_OSTREAM % (function_name, function_name)
            return str_function, ""
        if ('std::istream &' in '%s' % param_type) or ('Standard_IStream' in param_type):
            return TEMPLATE_ISTREAM % (function_name, function_name), ""
    if function_name == "DumpJson":
        str_function = TEMPLATE_DUMPJSON
        return str_function, ""
    # enable autocompactargs feature to enable compilation with swig>3.0.3
    str_function = '\t\t/****************** %s ******************/\n' % function_name
    str_function += '\t\t%%feature("compactdefaultargs") %s;\n' % function_name
    str_function += process_function_docstring(f)
    str_function += "\t\t"
    # return type
    # Careful: for constructors, we have to remove the "void"
    # return type from the SWIG wrapper
    # otherwise it causes the compiler to fail
    # with "incorrect use of ..."
    # function name
    if f["constructor"]:
        return_type = ""
    else:
        return_type = adapt_return_type(f["rtnType"])
    if f['virtual']:
        return_type = 'virtual ' + return_type
    if f['static'] and 'static' not in return_type:
        return_type = 'static ' + return_type
    if f['static']:
        parent_class_name = f['parent']['name']
        if parent_class_name == CURRENT_MODULE:
            parent_class_name = parent_class_name.lower()
        if not "<" in parent_class_name:
            CURRENT_MODULE_PYI_STATIC_METHODS_ALIASES += "%s_%s = %s.%s\n" % (parent_class_name,
                                                                       function_name,
                                                                       parent_class_name,
                                                                       function_name)
    # Case where primitive values are accessed by reference
    # one method Get* that returns the object
    # one method Set* that sets the object
    if return_type in ['Standard_Integer &', 'Standard_Real &', 'Standard_Boolean &',
                       'Standard_Integer&', 'Standard_Real&', 'Standard_Boolean&']:
        logging.info('\tCreating Get and Set methods for method %s' % function_name)
        modified_return_type = return_type.split(" ")[0]
        # we compute the parameters type and name, seperated with comma
        getter_params_type_and_names = []
        getter_params_only_names = []
        getter_param_hints = ['self']
        for param in f["parameters"]:
            param_type_and_name = "%s %s" % (adapt_param_type(param["type"]), param["name"])
            getter_params_type_and_names.append(param_type_and_name)
            getter_params_only_names.append(param["name"])
            # process hints
            type_for_hint = adapt_type_for_hint(adapt_param_type(param["type"]))
            getter_param_hints.append("%s: %s" % (param["name"], 
                                                  type_for_hint))
            
            
        setter_params_type_and_names = getter_params_type_and_names + ['%s value' % modified_return_type]
        # the setter hint
        hint_output_type = adapt_type_for_hint(modified_return_type)
        hint_value = ['value: %s' % hint_output_type]
        setter_param_hints = getter_param_hints + hint_value

        getter_params_type_and_names_str_csv = ','.join(getter_params_type_and_names)
        setter_params_type_and_names_str_csv = ','.join(setter_params_type_and_names)
        getter_params_only_names_str_csv = ','.join(getter_params_only_names)

        str_function = TEMPLATE_GETTER_SETTER % (modified_return_type, function_name,
                                                 getter_params_type_and_names_str_csv,
                                                 modified_return_type,
                                                 function_name,
                                                 getter_params_only_names_str_csv,
                                                 function_name,
                                                 setter_params_type_and_names_str_csv,
                                                 function_name,
                                                 getter_params_only_names_str_csv)
        # process type hint for this case
        getter_hint_str = "\tdef Get%s(%s) -> %s: ...\n" % (function_name,
                                                            ', '.join(getter_param_hints),
                                                            hint_output_type)
        setter_hint_str = "\tdef Set%s(%s) -> None: ...\n" % (function_name,
                                                            ', '.join(setter_param_hints))

        # finally returns the method definition and hint
        type_hint_str = getter_hint_str + setter_hint_str
        return str_function, type_hint_str
    str_function += "%s " % return_type
    # function name
    str_function += "%s" % function_name
    # process parameters
    parameters_types_and_names = []
    parameters_definition_strs = []
    num_parameters = len(f["parameters"])
    for param in f["parameters"]:
        param_string = ""
        param_type = adapt_param_type(param["type"])

        if "Handle_T &" in param_type:
            return False, ""  # skip this function, it will raise a compilation exception, it's something like a template
        if ('Standard_IStream' in param_type or 'Standard_OStream' in  param_type) and num_parameters > 1:
            return "", ""  # skip this method TODO : wrap std:istream and std::ostream properly
        if 'array_size' in param:
            # create a list of types/names tuples
            # a liste with 3 items [type, name, default_value]
            # if there's no default value, False
            # other wise the default value as a string
            param_type_and_name = ["%s" % param_type, "%s[%s]" % (param["name"], param["array_size"])]
        else:
            param_type_and_name = ["%s" % param_type, "%s" % param["name"]]

        param_string += adapt_param_type_and_name(" ".join(param_type_and_name))

        if "defaultValue" in param:
            def_value = adapt_default_value_parmlist(param)
            param_string += " = %s" % def_value
            # we add the default value to the end of the list param_type_and_name
            param_type_and_name.append(def_value)

        parameters_types_and_names.append(param_type_and_name)
        parameters_definition_strs.append(param_string)
    # generate the parameters string
    str_function += "(" + ", ".join(parameters_definition_strs) + ");\n"
    #
    # The following stuff is all related to type hints
    # function type hints
    #
    canceled = False
    str_typehint = ""
    # below is the list of types returned by the method
    # generally, all c++ methods return either zero (void) values
    # or 1. In some special cases, by ef returned parameters are wrapped
    # to python types and added to the return values
    # thus, some method may return a tuple
    types_returned = ["%s" % adapt_type_for_hint(return_type)]  # by default, nothing
    if overload:
        str_typehint += "\t@overload\n"
    if "operator" not in function_name:
        all_parameters_type_hint = ['self']  #by default, this is a class method not static
        if f["constructor"]:
            # add the overload decorator to handle
            # multiple constructors
            str_typehint += "\tdef __init__("
        else:
            if f['static']:
                str_typehint += "\t@staticmethod\n"
                all_parameters_type_hint = []  # if static, not self
            str_typehint += "\tdef %s(" % function_name
        
        if parameters_types_and_names:
            for par in parameters_types_and_names:
                par_typ = adapt_type_for_hint(par[0])
                if not par_typ:
                    canceled = True
                    break
                # check if there is some OutValue
                ov = adapt_param_type_and_name(" ".join(par))
                if 'OutValue' in ov:
                    type_to_add = "%s" % adapt_type_for_hint(ov)
                    if types_returned[0] == "None":
                        types_returned[0] = type_to_add
                    else:
                        types_returned.append(type_to_add)
                    continue
                # if there's a default value, the type becomes Optional[type] = value
                if len(par) == 3:
                    hint_def_value, adapt_type_hint_default_value_success = adapt_type_hint_default_value(par[2])
                    if adapt_type_hint_default_value_success:
                      par_typ = "Optional[%s] = %s" % (par_typ, hint_def_value)
                    else:  # no default value
                      par_typ = "Optional[%s]" % par_typ
                par_nam, success = adapt_type_hint_parameter_name(par[1])
                if not success:
                    canceled = True
                if par_nam.endswith('_list'):  # it's a list
                    par_typ = "List[%s]" % par_typ
                all_parameters_type_hint.append("%s: %s" % (par_nam, par_typ))
        str_typehint += ', '.join(all_parameters_type_hint)
        if len(types_returned) == 1:
            returned_type_hint = types_returned[0]
        elif len(types_returned) > 1:  # it's a tuple
            returned_type_hint = "Tuple[%s]" % (", ".join(types_returned))
        else:
            raise AssertionError("Method should at least have one returned type.")
        str_typehint += ") -> %s: ...\n" % returned_type_hint
    else:
        str_typehint = ""
    if canceled:
        str_typehint = ""
    # if the function is HashCode, we add immediately after
    # an __hash__ overloading
    if function_name == "HashCode" and len(f["parameters"]) == 1:
        str_function += TEMPLATE_HASHCODE
    str_function = str_function.replace('const const', 'const') + '\n'
    return str_function, str_typehint


def process_free_functions(free_functions_list):
    """ process a string for free functions
    """
    str_free_functions = ""
    sorted_free_functions_list = sorted(free_functions_list, key=itemgetter('name'))
    for free_function in sorted_free_functions_list:
        ok_to_wrap = process_function(free_function)
        if ok_to_wrap:
            str_free_functions += ok_to_wrap
    return str_free_functions


def process_constructors(constructors_list):
    """ this function process constructors.
    The constructors_list is a list of constructors
    """
    # first, assume that all methods are constructors
    for c in constructors_list:
        if not c['constructor']:
            raise AssertioError("This method is not a constructor")
    # then we cound the number of available constructors
    number_of_constructors = len(constructors_list)
    # if there are more than one constructor, then the __init__ method
    # has to be tagged as overloaded using the @overload decorator
    need_overload = False
    if number_of_constructors > 1 :
        need_overload = True
        logging.info("\t[TypeHint] More than 1 constructor, @overload decorator needed.")
    # then process the constructors
    str_functions = ""
    type_hints = ""
    for constructor in constructors_list:
        ok_to_wrap, ok_hints = process_function(constructor, need_overload)
        if ok_to_wrap:
            str_functions += ok_to_wrap
            type_hints += ok_hints
    return str_functions, type_hints


def process_methods(methods_list):
    """ process a list of public process_methods
    """
    str_functions = ""
    type_hints = ""
    # sort methods according to the method name
    sorted_methods_list = sorted(methods_list, key=itemgetter('name'))
    # create a dict to map function names and the number of occurrences,
    # to determine whether or not use the @overload decorator
    for function in sorted_methods_list:
        # don't process friend methods
        need_overload = False
        if not function["friend"]:
            # check if this method is many times in the function list
            names_count = 0
            function_name = function['name']
            for f in sorted_methods_list:
                if f["name"] == function_name:
                    names_count += 1
            if names_count > 1:
                need_overload = True
            ok_to_wrap, ok_hints = process_function(function, need_overload)
            if ok_to_wrap:
                str_functions += ok_to_wrap
                type_hints += ok_hints
    return str_functions, type_hints


def must_ignore_default_destructor(klass):
    """ Some classes, like for instance BRepFeat_MakeCylindricalHole
    has a protected destructor that must explicitely be ignored
    This is done by the directive
    %ignore Class::~Class() just before the wrapper definition
    """
    class_protected_methods = klass['methods']['protected']
    for protected_method in class_protected_methods:
        if protected_method["destructor"]:
            return True
    class_private_methods = klass['methods']['private']
    # finally, return True, the default constructor can be safely defined
    for private_method in class_private_methods:
        if private_method["destructor"]:
            return True
    return False


def class_can_have_default_constructor(klass):
    """ Check if the class can have a defaultctor wrap
    or, if not, return False if the %nodefaultctor is required
    """
    if klass["name"] in NODEFAULTCTOR:
        return False
    # class must not be an abstract class
    if klass["abstract"]:
        logging.info("\tClass %s is abstract, using %%nodefaultctor directive." % klass["name"])
        return False
    # check if the class has at least one public constructor defined
    has_one_public_constructor = False
    class_public_methods = klass['methods']['public']
    for public_method in class_public_methods:
        if public_method["constructor"] and public_method['name'] == klass["name"]:
            has_one_public_constructor = True
    # we have to ensure that no private or protected constructor is defined
    # we look for protected () constructor
    has_one_protected_constructor = False
    class_protected_methods = klass['methods']['protected']
    for protected_method in class_protected_methods:
        if protected_method["constructor"] and protected_method['name'] == klass["name"]:
            has_one_protected_constructor = True
    # check for private constructor
    has_one_private_constructor = False
    class_private_methods = klass['methods']['private']
    for private_method in class_private_methods:
        if private_method["constructor"] and private_method['name'] == klass["name"]:
            has_one_private_constructor = True
    if ((has_one_private_constructor and not has_one_public_constructor) or
            (has_one_protected_constructor and not has_one_public_constructor)):
        return False
    #finally returns True, no need to use the %nodefaultctor
    return True


def build_inheritance_tree(classes_dict):
    """ From the classes dict, return a list of classes
    with the class ordered from the most abtract to
    the more specialized. The more abstract will be
    processed first.
    """
    global ALL_STANDARD_TRANSIENTS
    # first, we build two dictionaries
    # the first one, level_0_classes
    # contain class names that does not inherit from
    # any other class
    # they will be processed first
    level_0_classes = []
    # the inheritance dict contains the relationships
    # betwwen a class and its upper class.
    # the dict schema is as the following :
    # inheritance_dict = {'base_class_name': 'upper_class_name'}
    inheritance_dict = {}
    for klass in classes_dict.values():
        class_name = klass["name"]
        upper_classes = klass["inherits"]
        nbr_upper_classes = len(upper_classes)
        if nbr_upper_classes == 0:
            level_0_classes.append(class_name)
        # if class has one or more ancestors
        # for class with one or two ancestors, let's process them
        # the same. Anyway, whan there are two ancestors (only a few cases),
        # one of the two ancestors come from another module.
        elif nbr_upper_classes == 1:
            upper_class_name = upper_classes[0]["class"]
            # if the upper class depends on another module
            # add it to the level 0 list.
            if upper_class_name.split("_")[0] != CURRENT_MODULE:
                level_0_classes.append(class_name)
            # else build the inheritance tree
            else:
                inheritance_dict[class_name] = upper_class_name
        elif nbr_upper_classes == 2:
            # if one, or the other
            upper_class_name_1 = upper_classes[0]["class"]
            class_1_module = upper_class_name_1.split("_")[0]
            upper_class_name_2 = upper_classes[1]["class"]
            class_2_module = upper_class_name_2.split("_")[0]
            if class_1_module == upper_class_name_2 == CURRENT_MODULE:
                logging.warning("Tthis is a special case, where the 2 ancestors belong the same module. Class %s skipped." % class_name)
            if class_1_module == CURRENT_MODULE:
                inheritance_dict[class_name] = upper_class_name_1
            elif class_2_module == CURRENT_MODULE:
                inheritance_dict[class_name] = upper_class_name_2
            elif upper_class_name_1 == upper_class_name_2:  # the samemodule, but external, not the current one
                level_0_classes.append(class_name)
            inheritance_dict[class_name] = upper_class_name_1
        else:
            # prevent multiple inheritance: OCE only has single
            # inheritance
            logging.warning("Class %s has %i ancestors and is skipped." % (class_name, nbr_upper_classes))
    # then, after that, we process both dictionaries, list so
    # that we reorder class.
    # first, we build something called the inheritance_depth.
    # that is to say a dict with the class name and the number of upper classes
    # inheritance_depth = {'Standard_Transient':0, 'TopoDS_Shape':1}
    inheritance_depth = {}
    # first we fill in with level_0:
    for class_name in level_0_classes:
        inheritance_depth[class_name] = 0
    upper_classes = inheritance_dict.values()
    for base_class_name in inheritance_dict:
        tmp = base_class_name
        i = 0
        while tmp in inheritance_dict:
            tmp = inheritance_dict[tmp]
            i += 1
        inheritance_depth[base_class_name] = i
    # after that, we traverse the inheritance depth dict
    # to order classes names according to their depth.
    # first classes with level 0, then 1, 2 etc.
    # at last, we return the class_list containing a list
    # of ordered classes.
    class_list = []
    for class_name, depth_value in sorted(inheritance_depth.items(),
                                          key=lambda kv: (kv[1], kv[0])):
        if class_name in classes_dict:  # TODO: should always be the case!
            class_list.append(classes_dict[class_name])
    # Then we build the list of all classes that inherit from Standard_Transient
    # at some point. These classes will need the %wrap_handle and %make_alias_macros
    for klass in class_list:
        upper_class = klass['inherits']
        class_name = klass['name']
        if upper_class:
            upper_class_name = klass['inherits'][0]['class']
            if upper_class_name in ALL_STANDARD_TRANSIENTS:
                # this class inherits from a Standard_Transient base class
                # so we add it to the ALL_STANDARD_TRANSIENTS list:
                if not klass in ALL_STANDARD_TRANSIENTS:
                    ALL_STANDARD_TRANSIENTS.append(class_name)
    return class_list


def fix_type(type_str):
    type_str = type_str.replace("Standard_Boolean &", "bool")
    type_str = type_str.replace("Standard_Boolean", "bool")
    type_str = type_str.replace("Standard_Real", "float")
    type_str = type_str.replace("Standard_Integer", "int")
    type_str = type_str.replace("const", "")
    type_str = type_str.replace("& &", "&")
    return type_str


def process_harray1():
    """ special wrapper for NCollection_HArray1
    Returns both the definition and the hint
    """
    wrapper_str = "/* harray1 classes */\n"
    pyi_str = "\n# harray1 classes\n"
    for HClassName in ALL_HARRAY1:
        if HClassName.startswith(CURRENT_MODULE + "_"):
            _Array1Type_ = ALL_HARRAY1[HClassName]
            wrapper_for_harray1 = HARRAY1_TEMPLATE.replace("HClassName", HClassName)
            wrapper_for_harray1 = wrapper_for_harray1.replace("_Array1Type_", _Array1Type_)
            wrapper_str += wrapper_for_harray1
            # type hint
            pyi_str_for_harray1 = HARRAY1_TEMPLATE_PYI.replace("HClassName", HClassName)
            pyi_str_for_harray1 = pyi_str_for_harray1.replace("_Array1Type_", _Array1Type_)
            pyi_str += pyi_str_for_harray1
    return wrapper_str, pyi_str


def process_harray2():
    wrapper_str = "/* harray2 classes */"
    pyi_str = "# harray2 classes\n"
    for HClassName in ALL_HARRAY2:
        if HClassName.startswith(CURRENT_MODULE + "_"):
            _Array2Type_ = ALL_HARRAY2[HClassName]
            wrapper_for_harray2 = HARRAY2_TEMPLATE.replace("HClassName", HClassName)
            wrapper_for_harray2 = wrapper_for_harray2.replace("_Array2Type_", _Array2Type_)
            wrapper_str += wrapper_for_harray2
            # type hint
            pyi_str_for_harray2 = HARRAY2_TEMPLATE_PYI.replace("HClassName", HClassName)
            pyi_str_for_harray2 = pyi_str_for_harray2.replace("_Array2Type_", _Array2Type_)
            pyi_str += pyi_str_for_harray2
    wrapper_str += "\n"
    return wrapper_str, pyi_str


def process_hsequence():
    wrapper_str = "/* hsequence classes */"
    pyi_str = "# hsequence classes\n"
    for HClassName in ALL_HSEQUENCE:
        if HClassName.startswith(CURRENT_MODULE + "_"):
            _SequenceType_ = ALL_HSEQUENCE[HClassName]
            wrapper_for_hsequence = HSEQUENCE_TEMPLATE.replace("HClassName", HClassName)
            wrapper_for_hsequence = wrapper_for_hsequence.replace("_SequenceType_", _SequenceType_)
            wrapper_str += wrapper_for_hsequence
            # type hint
            pyi_str_for_hsequence  = HSEQUENCE_TEMPLATE_PYI.replace("HClassName", HClassName)
            pyi_str_for_hsequence = pyi_str_for_hsequence.replace("_SequenceType_", _SequenceType_)
            pyi_str += pyi_str_for_hsequence
    wrapper_str += "\n"
    pyi_str += "\n"
    return wrapper_str, pyi_str


def process_handles(classes_dict, exclude_classes, exclude_member_functions):
    """ Check wether a class has to be wrapped as a handle
    using the wrap_handle swig macro.
    This code is a bit redundant with process_classes, but this step
    appeared to be placed before typedef ans templates definition
    """
    wrap_handle_str = "/* handles */\n"
    if exclude_classes == ['*']:  # don't wrap any class
        return ""
    inheritance_tree_list = build_inheritance_tree(classes_dict)
    for klass in inheritance_tree_list:
        # class name
        class_name = klass["name"]
        if class_name in exclude_classes:
            # if the class has to be excluded,
            # we go on with the next one to be processed
            continue
        if check_has_related_handle(class_name) or class_name == "Standard_Transient":
            wrap_handle_str += "%%wrap_handle(%s)\n" % class_name
    for HClassName in ALL_HARRAY1:
        if HClassName.startswith(CURRENT_MODULE + "_"):
            wrap_handle_str += "%%wrap_handle(%s)\n" % HClassName
    for HClassName in ALL_HARRAY2:
        if HClassName.startswith(CURRENT_MODULE + "_"):
            wrap_handle_str += "%%wrap_handle(%s)\n" % HClassName
    for HClassName in ALL_HSEQUENCE:
        if HClassName.startswith(CURRENT_MODULE + "_"):
            wrap_handle_str += "%%wrap_handle(%s)\n" % HClassName
    wrap_handle_str += "/* end handles declaration */\n\n"
    return wrap_handle_str


def process_classes(classes_dict, exclude_classes, exclude_member_functions):
    """ Generate the SWIG string for the class wrapper.
    Works from a dictionary of all classes, generated with CppHeaderParser.
    All classes but the ones in exclude_classes are wrapped.
    excludes_classes is a list with the class names to exclude_classes
    exclude_member_functions is a dict with classes names as keys and member
    function names as values
    """
    global NB_TOTAL_CLASSES
    if exclude_classes == ['*']:  # don't wrap any class
        # that is to say we add all classes to the list of exclude_member_functions
        new_exclude_classes= []
        for klass in classes_dict:
            class_name_to_exclude = klass.split('::')[0]
            class_name_to_exclude = class_name_to_exclude.split('<')[0]
            if class_name_to_exclude not in new_exclude_classes:
                new_exclude_classes.append(class_name_to_exclude)
        exclude_classes = new_exclude_classes.copy()
        #return "", ""
    class_def_str = ""  # the string for class definition
    class_pyi_str = ""  # the string for class type hints

    inheritance_tree_list = build_inheritance_tree(classes_dict)
    for klass in inheritance_tree_list:
        # class name
        class_name = klass["name"]
        # header
        stars = ''.join(['*' for i in range(len(class_name) + 9)])
        class_def_str += "/%s\n* class %s *\n%s/\n" % (stars, class_name, stars)
        #
        if class_name in exclude_classes:
            # if the class has to be excluded,
            # we go on with the next one to be processed
            continue
        # ensure the class returned by CppHeader is defined in this module
        # otherwise we go on with the next class
        if not class_name.startswith(CURRENT_MODULE):
            continue
        # we rename the class if the module is the same name
        # for instance TopoDS is both a module and a class
        # then we rename the class with lowercase
        logging.info(class_name)
        # the class type hint
        class_name_for_pyi = class_name.split('<')[0]
        
        if class_name == CURRENT_MODULE:
            class_def_str += "%%rename(%s) %s;\n" % (class_name.lower(), class_name)
            class_name_for_pyi = class_name_for_pyi.lower()
        # then process the class itself
        if not class_can_have_default_constructor(klass):
            class_def_str += "%%nodefaultctor %s;\n" % class_name
        if must_ignore_default_destructor(klass):
        # check if the destructor is protected or private
            class_def_str += "%%ignore %s::~%s();\n" % (class_name, class_name)
        # then defines the wrapper
        class_def_str += "class %s" % class_name
        class_pyi_str += "\nclass %s" % class_name_for_pyi  # type hints
        # inheritance process
        inherits_from = klass["inherits"]
        if inherits_from: # at least 1 ancestor
            inheritance_name = inherits_from[0]["class"]
            check_dependency(inheritance_name)
            inheritance_access = inherits_from[0]["access"]
            class_def_str += " : %s %s" % (inheritance_access, inheritance_name)
            class_pyi_str += "("
            if not "::" in inheritance_name and not "<" in inheritance_name:
                class_pyi_str += "%s" % inheritance_name
            if len(inherits_from) == 2: ## 2 ancestors
                inheritance_name_2 = inherits_from[1]["class"]
                check_dependency(inheritance_name_2)
                inheritance_access_2 = inherits_from[1]["access"]
                class_def_str += ", %s %s" % (inheritance_access_2, inheritance_name_2)
                class_pyi_str += ", %s" % inheritance_name_2
            class_pyi_str += ")"
        class_pyi_str += ":\n"
        class_pyi_str += "\tpass\n"  # TODO CHANGE
        class_def_str += " {\n"
        # process class typedefs here
        typedef_str = '\tpublic:\n'
        for typedef_value in list(klass["typedefs"]['public']):
            if ')' in typedef_value:
                continue
            typedef_str += "typedef %s %s;\n" % (klass._public_typedefs[typedef_value], typedef_value)
        class_def_str += typedef_str
        # process class enums here
        class_enums_list = klass["enums"]['public']
        ###### Nested classes
        nested_classes = klass["nested_classes"]
        for n in nested_classes:
            nested_class_name = n["name"]
            # skip anon structs, for instance in AdvApp2Var_SysBase
            if "anon-struct" in nested_class_name:
                continue
            logging.info("\tWrap nested class %s::%s" % (class_name, nested_class_name))
            class_def_str += "\t\tclass " + nested_class_name + " {};\n"
        ####### class enums
        if class_enums_list:
            class_enum_def, class_enum_pyi = process_enums(class_enums_list)
            class_def_str += class_enum_def
        # process class properties here
        properties_str = ''
        for property_value in list(klass["properties"]['public']):
            if 'NCollection_Vec2' in property_value['type']: # issue in Aspect_Touch
                logging.warning('Wrong type in class property : NCollection_Vec2')
                continue
            if 'using' in property_value['type']:
                logging.warning('Wrong type in class property : using')
                continue
            if 'return' in property_value['type']:
                logging.warning('Wrong type in class property : return')
                continue
            if 'std::map<' in property_value['type']:
                logging.warning('Wrong type in class property std::map')
                continue
            if property_value['constant'] or 'virtual' in property_value['raw_type'] or 'allback' in property_value['raw_type']:
                continue
            if 'array_size' in property_value:
                temp = "\t\t%s %s[%s];\n" % (fix_type(property_value['type']), property_value['name'], property_value['array_size'])
            else:
                temp = "\t\t%s %s;\n" % (fix_type(property_value['type']), property_value['name'])
            properties_str += temp
        # @TODO : classe typedefs (for instance BRepGProp_MeshProps)
        class_def_str += properties_str
        # process methods here
        class_public_methods = klass['methods']['public']
        # remove, from this list, all functions that
        # are excluded
        try:
            members_functions_to_exclude = exclude_member_functions[class_name]
        except KeyError:
            members_functions_to_exclude = []
        # if ever the header defines DEFINE STANDARD ALLOC
        # then we wrap a copy constructor. Very convenient
        # to create python classes that inherit from OCE ones!
        if class_name in ['TopoDS_Shape', 'TopoDS_Vertex']:
            class_def_str += '\t\t%feature("autodoc", "1");\n'
            class_def_str += '\t\t%s(const %s arg0);\n' % (class_name, class_name)
        methods_to_process = filter_member_functions(class_name, class_public_methods, members_functions_to_exclude, klass["abstract"])
        # amons all methods, we first process constructors, than the others
        constructors, other_methods =  methods_to_process
        # first constructors
        constructors_definitions, constructors_type_hints = process_constructors(constructors)
        class_def_str += constructors_definitions
        class_pyi_str += constructors_type_hints
        # and the other methods
        other_method_definitions, other_method_type_hints = process_methods(other_methods)
        class_def_str += other_method_definitions
        class_pyi_str += other_method_type_hints

        # after that change, we remove the "pass" if it appears to be unnecessary
        # for example
        # class gp_Ax22d:
        #    pass
        #    def Location
        # should be
        # class gp_Ax22d:
        #    def Location
        class_pyi_str = class_pyi_str.replace('pass\n\t@overload', '@overload')
        class_pyi_str = class_pyi_str.replace('pass\n\tdef', 'def')
        class_pyi_str = class_pyi_str.replace('pass\n\t@staticmethod', '@staticmethod')
        # a special wrapper template for TDF_Label
        # We add a special method for recovering label names
        if class_name == "TDF_Label":
            class_def_str += '%feature("autodoc", "Returns the label name") GetLabelName;\n'
            class_def_str += '\t\t%extend{\n'
            class_def_str += '\t\t\tstd::string GetLabelName() {\n'
            class_def_str += '\t\t\tstd::string txt;\n'
            class_def_str += '\t\t\tHandle(TDataStd_Name) name;\n'
            class_def_str += '\t\t\tif (!self->IsNull() && self->FindAttribute(TDataStd_Name::GetID(),name)) {\n'
            class_def_str += '\t\t\tTCollection_ExtendedString extstr = name->Get();\n'
            class_def_str += '\t\t\tchar* str = new char[extstr.LengthOfCString()+1];\n'
            class_def_str += '\t\t\textstr.ToUTF8CString(str);\n'
            class_def_str += '\t\t\ttxt = str;\n'
            class_def_str += '\t\t\tdelete[] str;}\n'
            class_def_str += '\t\t\treturn txt;}\n'
            class_def_str += '\t\t};\n'
        # then terminate the class definition
        class_def_str += "};\n\n"
        #
        # at last, check if there is a related handle
        # if yes, we integrate it into it's shadow class
        # TODO: check that the following is not restricted
        # to protected destructors !
        class_def_str += '\n'
        if check_has_related_handle(class_name) or class_name == "Standard_Transient":
            # Extend class by GetHandle method
            class_def_str += '%%make_alias(%s)\n\n' % class_name

        # We add pickling for TopoDS_Shapes
        if class_name == 'TopoDS_Shape':
            class_def_str += '%extend TopoDS_Shape {\n%pythoncode {\n'
            class_def_str += '\tdef __getstate__(self):\n'
            class_def_str += '\t\tfrom .BRepTools import BRepTools_ShapeSet\n'
            class_def_str += '\t\tss = BRepTools_ShapeSet()\n'
            class_def_str += '\t\tss.Add(self)\n'
            class_def_str += '\t\tstr_shape = ss.WriteToString()\n'
            class_def_str += '\t\tindx = ss.Locations().Index(self.Location())\n'
            class_def_str += '\t\treturn str_shape, indx\n'
            class_def_str += '\tdef __setstate__(self, state):\n'
            class_def_str += '\t\tfrom .BRepTools import BRepTools_ShapeSet\n'
            class_def_str += '\t\ttopods_str, indx = state\n'
            class_def_str += '\t\tss = BRepTools_ShapeSet()\n'
            class_def_str += '\t\tss.ReadFromString(topods_str)\n'
            class_def_str += '\t\tthe_shape = ss.Shape(ss.NbShapes())\n'
            class_def_str += '\t\tlocation = ss.Locations().Location(indx)\n'
            class_def_str += '\t\tthe_shape.Location(location)\n'
            class_def_str += '\t\tself.this = the_shape.this\n'
            class_def_str += '\t}\n};\n'
        # for each class, overload the __repr__ method to avoid things like:
        # >>> print(box)
        #<OCC.TopoDS.TopoDS_Shape; proxy of <Swig Object of type 'TopoDS_Shape *' at 0x02
        #BCF770> >
        class_def_str += '%%extend %s {\n' % class_name
        class_def_str += '\t%' + 'pythoncode {\n'
        class_def_str += '\t__repr__ = _dumps_object\n'
        # we process methods that are excluded fro mthe wrapper
        # they used to be skipped, but it's better to explicitely
        # raise a MethodNotWrappedError exception
        for excluded_method_name in members_functions_to_exclude:
            if excluded_method_name != 'Handle':
                class_def_str += '\n\t@methodnotwrapped\n'
                class_def_str += '\tdef %s(self):\n\t\tpass\n' % excluded_method_name
        class_def_str += '\t}\n};\n\n'
        # increment global number of classes
        NB_TOTAL_CLASSES += 1
    #
    # Finally, we create a python proxy for each exclude class
    # to raise a python exception ClassNotWrapped
    # and we do the same in the stub file
    if exclude_classes:  # if the list is not empty
        class_def_str += "/* python proxy for excluded classes */\n"
        class_def_str += "%pythoncode {\n"
        for excluded_class in exclude_classes:
            class_def_str += "@classnotwrapped\n"
            class_def_str += "class %s:\n\tpass\n\n" % excluded_class
            class_pyi_str += "\n#classnotwrapped\n"
            class_pyi_str += "class %s: ...\n" % excluded_class
        class_def_str += "}\n"
        class_def_str += "/* end python proxy for excluded classes */\n"
    return class_def_str, class_pyi_str


def is_module(module_name):
    """ Checks if the name passed as a parameter is
    (or is not) a module that aims at being wrapped.
    'Standard' should return True
    'inj' or whatever should return False
    """
    for mod in OCE_MODULES:
        if mod[0] == module_name:
            return True
    return False


def test_is_module():
    assert is_module('Standard') is True
    assert is_module('something') is False


def parse_module(module_name):
    """ A module is defined by a set of headers. For instance AIS,
    gp, BRepAlgoAPI etc. For each module, generate three or more
    SWIG files. This parser returns :
    module_enums, module_typedefs, module_classes
    """
    module_headers = glob.glob('%s/%s_*.hxx' % (OCE_INCLUDE_DIR, module_name))
    module_headers += glob.glob('%s/%s.hxx' % (OCE_INCLUDE_DIR, module_name))
    # filter those headers
    module_headers = filter_header_list(module_headers, HXX_TO_EXCLUDE_FROM_CPPPARSER)
    cpp_headers = map(parse_header, module_headers)
    module_typedefs = {}
    module_enums = []
    module_classes = {}
    module_free_functions = []
    for header in cpp_headers:
        # build the typedef dictionary
        module_typedefs.update(header.typedefs)
        # build the enum list
        module_enums += header.enums
        # build the class dictionary
        module_classes.update(header.classes.items())
        # build the free functions list
        module_free_functions += header.functions
    return module_typedefs, module_enums, module_classes, module_free_functions


class ModuleWrapper:
    def __init__(self, module_name, additional_dependencies,
                 exclude_classes, exclude_member_functions):
        # Reinit global variables
        global CURRENT_MODULE, CURRENT_MODULE_PYI_STATIC_METHODS_ALIASES, PYTHON_MODULE_DEPENDENCY
        CURRENT_MODULE = module_name
        CURRENT_MODULE_PYI_STATIC_METHODS_ALIASES = ""
        # all modules depend, by default, upon Standard, NCollection and others
        if module_name not in ['Standard', 'NCollection']:
            PYTHON_MODULE_DEPENDENCY = ['Standard', 'NCollection']
            reset_header_depency()
        else:
            PYTHON_MODULE_DEPENDENCY = []

        logging.info("## Processing module %s" % module_name)
        self._module_name = module_name
        self._module_docstring = get_module_docstring(module_name)
        # parse
        typedefs, enums, classes, free_functions = parse_module(module_name)
        #enums
        self._enums_str, self._enums_pyi_str = process_enums(enums)
        # handles
        self._wrap_handle_str = process_handles(classes, exclude_classes,
                                                exclude_member_functions)
        # templates and typedefs
        self._typedefs_str, self._typedefs_pyi_str = process_typedefs(typedefs)
        #classes
        self._classes_str, self._classes_pyi_str = process_classes(classes,
                                                                   exclude_classes,
                                                                   exclude_member_functions)
        # special classes for NCollection_HArray1, NCollection_HArray2 and NCollection_HSequence
        harray1_def_str, harray1_pyi_str = process_harray1()
        self._classes_str += harray1_def_str
        self._classes_pyi_str += harray1_pyi_str

        harray2_def_str, harray2_pyi_str = process_harray2()
        self._classes_str += harray2_def_str
        self._classes_pyi_str += harray2_pyi_str

        hsequence_def_str, hsequence_pyi_str = process_hsequence()
        self._classes_str += hsequence_def_str
        self._classes_pyi_str += hsequence_pyi_str

        # free functions
        self._free_functions_str, self._free_functions_pyi_str = process_methods(free_functions)
        # other dependencies
        self._additional_dependencies = additional_dependencies + HEADER_DEPENDENCY
        # generate swig file
        self.generate_SWIG_files()

    def generate_SWIG_files(self):
        #
        # The SWIG .i file
        #
        if GENERATE_SWIG_FILES:
            swig_interface_file = open(os.path.join(SWIG_OUTPUT_PATH, "%s.i" % self._module_name), "w")
            # write header
            swig_interface_file.write(LICENSE_HEADER)
            # write module docstring
            # for instante define GPDOCSTRING
            docstring_macro = "%sDOCSTRING" % self._module_name.upper()
            swig_interface_file.write('%%define %s\n' % docstring_macro)
            swig_interface_file.write('"%s"\n' % self._module_docstring)
            swig_interface_file.write('%enddef\n')
            # module name
            swig_interface_file.write('%%module (package="OCC.Core", docstring=%s) %s\n\n' % (docstring_macro, self._module_name))
            # write windows pragmas to avoid compiler errors
            swig_interface_file.write(WIN_PRAGMAS)
            # common includes
            includes = ["CommonIncludes", "ExceptionCatcher",
                        "FunctionTransformers", "Operators", "OccHandle"]
            for include in includes:
                swig_interface_file.write("%%include ../common/%s.i\n" % include)
            swig_interface_file.write("\n\n")
            # Here we write required dependencies, headers, as well as
            # other swig interface files
            swig_interface_file.write("%{\n")
            if self._module_name == "Adaptor3d": # occt bug in headr file, won't compile otherwise
                swig_interface_file.write("#include<Adaptor2d_HCurve2d.hxx>\n")
            if self._module_name == "AdvApp2Var": # windows compilation issues
                swig_interface_file.write("#if defined(_WIN32)\n#include <windows.h>\n#endif\n")
            if self._module_name in ["BRepMesh", "XBRepMesh"]: # wrong header order with gcc4 issue #63
                swig_interface_file.write("#include<BRepMesh_Delaun.hxx>\n")
            if self._module_name == "ShapeUpgrade":
                swig_interface_file.write("#include<Precision.hxx>\n#include<ShapeUpgrade_UnifySameDomain.hxx>\n")
            module_headers = glob.glob('%s/%s_*.hxx' % (OCE_INCLUDE_DIR, self._module_name))
            module_headers += glob.glob('%s/%s.hxx' % (OCE_INCLUDE_DIR, self._module_name))
            module_headers.sort()

            mod_header = open(os.path.join(HEADERS_OUTPUT_PATH, "%s_module.hxx" % self._module_name), "w")
            mod_header.write(LICENSE_HEADER)
            mod_header.write("#ifndef %s_HXX\n" % self._module_name.upper())
            mod_header.write("#define %s_HXX\n\n" % self._module_name.upper())
            mod_header.write("\n")

            for module_header in filter_header_list(module_headers, HXX_TO_EXCLUDE_FROM_BEING_INCLUDED):
                if not os.path.basename(module_header) in HXX_TO_EXCLUDE_FROM_BEING_INCLUDED:
                    mod_header.write("#include<%s>\n" % os.path.basename(module_header))
            mod_header.write("\n#endif // %s_HXX\n" % self._module_name.upper())

            swig_interface_file.write("#include<%s_module.hxx>\n" % self._module_name)
            swig_interface_file.write("\n//Dependencies\n")
            # Include all dependencies
            for dep in PYTHON_MODULE_DEPENDENCY:
                swig_interface_file.write("#include<%s_module.hxx>\n" % dep)
            for add_dep in self._additional_dependencies:
                swig_interface_file.write("#include<%s_module.hxx>\n" % add_dep)

            swig_interface_file.write("%};\n")
            for dep in PYTHON_MODULE_DEPENDENCY:
                if is_module(dep):
                    swig_interface_file.write("%%import %s.i\n" % dep)
            #
            # The Exceptions and decorator
            #
            swig_interface_file.write("\n%pythoncode {\n")
            swig_interface_file.write("from enum import IntEnum\n")
            swig_interface_file.write("from OCC.Core.Exception import *\n")
            swig_interface_file.write("};\n\n")        

            # for NCollection, we add template classes that can be processed
            # automatically with SWIG
            if self._module_name == "NCollection":
                swig_interface_file.write(NCOLLECTION_HEADER_TEMPLATE)
            if self._module_name == "BVH":
                swig_interface_file.write(BVH_HEADER_TEMPLATE)
            if self._module_name == "Prs3d":
                swig_interface_file.write(PRS3D_HEADER_TEMPLATE)
            if self._module_name == "Graphic3d":
                swig_interface_file.write(GRAPHIC3D_DEFINE_HEADER)
            if self._module_name == "BRepAlgoAPI":
                swig_interface_file.write(BREPALGOAPI_HEADER)
            # write public enums
            swig_interface_file.write(self._enums_str)
            # write wrap_handles
            swig_interface_file.write(self._wrap_handle_str)
            # write type_defs
            swig_interface_file.write(self._typedefs_str)
            # write classes_definition
            swig_interface_file.write(self._classes_str)
            # write free_functions definition
            #TODO: we should write free functions here,
            # but it sometimes fail to compile
            #swig_interface_file.write(self._free_functions_str)
            swig_interface_file.close()

        #
        # write pyi stub file
        #
        pyi_stub_file = open(os.path.join(SWIG_OUTPUT_PATH, "%s.pyi" % self._module_name), "w")
        # first write the header
        pyi_stub_file.write("from enum import IntEnum\n")
        pyi_stub_file.write("from typing import overload, NewType, Optional, Tuple\n\n")

        #pyi_stub_file.write("from OCC.Core.%s import *\n" % CURRENT_MODULE)
        for dep in PYTHON_MODULE_DEPENDENCY:
            if is_module(dep):
                pyi_stub_file.write("from OCC.Core.%s import *\n" % dep)
        # we create NewTypes for some typedef which are just aliases. For instance, Prs3d_Presentation
        # type is not defined in Python, whereas it's just an alias for Graphic3d_Structure. Then we define
        # Prs3d_Presentation = NewType("Prs3d_Presentation", Graphic3d_Structure)
        pyi_stub_file.write(self._typedefs_pyi_str)
        # enums, wrapped by python class
        pyi_stub_file.write(self._enums_pyi_str)
        # then write classes and methods
        pyi_stub_file.write(self._classes_pyi_str)
        # and we finally write the aliases for static methods
        pyi_stub_file.write(CURRENT_MODULE_PYI_STATIC_METHODS_ALIASES)
        pyi_stub_file.close()


def process_module(module_name):
    all_modules = OCE_MODULES
    module_exist = False
    for module in all_modules:
        if module[0] == module_name:
            module_exist = True
            module_additionnal_dependencies = module[1]
            module_exclude_classes = module[2]
            if len(module) == 4:
                modules_exclude_member_functions = module[3]
            else:
                modules_exclude_member_functions = {}
            #print("Next to be processed : %s " % module_name)
            ModuleWrapper(module_name,
                          module_additionnal_dependencies,
                          module_exclude_classes,
                          modules_exclude_member_functions)
    if not module_exist:
        raise NameError('Module %s not defined' % module_name)


def process_toolkit(toolkit_name):
    """ Generate wrappers for modules depending on a toolkit
    For instance : TKernel, TKMath etc.
    """
    modules_list = TOOLKITS[toolkit_name]
    logging.info("Processing toolkit %s ===" % toolkit_name)
    for module in sorted(modules_list):
        process_module(module)


def process_all_toolkits():
    for toolkit in sorted(TOOLKITS):
        process_toolkit(toolkit)


def run_unit_tests():
    test_is_module()
    test_filter_header_list()
    test_get_all_module_headers()
    test_adapt_return_type()
    test_filter_typedefs()
    test_adapt_function_name()
    test_adapt_param_type_and_name()
    test_adapt_default_value()
    test_check_dependency()
    test_get_type_for_ncollection_array()


if __name__ == '__main__':
    # do it each time, does not take too much time, prevent regressions
    run_unit_tests()
    logging.info(get_log_header())
    start_time = time.perf_counter()
    if len(sys.argv) > 1:
        for module_to_process in sys.argv[1:]:
            process_module(module_to_process)
    else:
        process_all_toolkits()
    end_time = time.perf_counter()
    total_time = end_time - start_time
    # footer
    logging.info(get_log_footer(total_time))
    logging.info("Number of classes: %i" % NB_TOTAL_CLASSES)
    logging.info("Number of methods: %i" % NB_TOTAL_METHODS)
